"""Provider-neutral Phase 3 implementation execution contract.

The worker asks a managed inference provider for a *reviewable* change set. It
never applies model output directly to the production repository and it never
turns an invalid response into a successful run. Heroku and RunPod both use
the same strict JSON contract so either provider can be selected or used as a
fallback.
"""

from __future__ import annotations

import json
import posixpath
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..errors import ApiError, ValidationError
from ..inference.openai_compatible import ChatCompletionTransportError, request_chat_completion
from ..security.network import validate_external_https_url


class AgentExecutionError(ApiError):
    def __init__(self, message: str = "Agent execution failed", details: dict | None = None):
        super().__init__(message, code="agent_execution_error", status=502, details=details)


@dataclass(frozen=True)
class GeneratedChange:
    path: str
    action: str
    diff: str


@dataclass(frozen=True)
class ExecutionResult:
    provider: str
    changes: list[GeneratedChange]
    self_review: dict
    evidence: dict


class AgentExecutor(ABC):
    @abstractmethod
    def execute(self, run, plan: dict, checkpoint: dict | None = None) -> ExecutionResult:
        """Execute a reviewed plan through a provider implementation."""
        ...


class ManagedInferenceAgentExecutor(AgentExecutor):
    """Call OpenAI-compatible, Heroku, and/or RunPod providers."""

    def __init__(self, config: dict, model_config: dict | None = None):
        self.config = config
        self.model_config = model_config or {}
        provider_value = self.model_config.get("provider") or config.get(
            "AGENT_IMPLEMENTATION_PROVIDER", "disabled"
        )
        self.providers = [
            value.strip().lower() for value in str(provider_value).split(",") if value.strip()
        ]
        if not self.providers or self.providers == ["disabled"]:
            raise AgentExecutionError(
                "Phase 3 implementation worker is disabled; configure "
                "AGENT_IMPLEMENTATION_PROVIDER as openai_compatible, heroku, or runpod"
            )
        invalid = set(self.providers) - {"openai_compatible", "heroku", "runpod"}
        if invalid:
            raise ValidationError("AGENT_IMPLEMENTATION_PROVIDER entries must be openai_compatible, heroku or runpod")
        self.timeout = int(
            self.model_config.get(
                "timeout_seconds", config.get("AGENT_IMPLEMENTATION_TIMEOUT_SECONDS", 180)
            )
        )
        self.max_tokens = int(
            self.model_config.get("max_tokens", config.get("OPENAI_COMPATIBLE_MAX_TOKENS", config.get("HEROKU_INFERENCE_MAX_TOKENS", 4096)))
        )

    @property
    def provider(self) -> str:
        return "+".join(self.providers)

    def execute(self, run, plan: dict, checkpoint: dict | None = None) -> ExecutionResult:
        prompt = _implementation_prompt(run, plan, checkpoint)
        failures = []
        for position, provider in enumerate(self.providers, start=1):
            try:
                payload = self._request(provider, prompt)
                result = parse_execution_result(payload)
                evidence = dict(result.evidence)
                usage = payload.get("usage") if isinstance(payload, dict) else None
                if isinstance(usage, dict):
                    evidence["provider_usage"] = usage
                provider_cost = payload.get("cost") if isinstance(payload, dict) else None
                if isinstance(provider_cost, (int, float)) and not isinstance(provider_cost, bool):
                    evidence["provider_cost"] = provider_cost
                evidence["provider_attempt"] = {"provider": provider, "position": position}
                return ExecutionResult(
                    provider=provider,
                    changes=result.changes,
                    self_review=result.self_review,
                    evidence=evidence,
                )
            except AgentExecutionError as exc:
                failures.append({"provider": provider, "message": exc.message, "details": exc.details})
        raise AgentExecutionError(
            "All configured implementation providers failed",
            details={"attempts": failures, "provider_count": len(self.providers)},
        )

    def _request(self, provider: str, prompt: str) -> dict:
        payload = self._payload(provider, prompt)
        if provider in {"heroku", "openai_compatible"}:
            base_url, key = self._endpoint(provider)
            try:
                return request_chat_completion(
                    base_url=base_url,
                    api_key=key,
                    payload=payload,
                    timeout=self.timeout,
                )
            except ChatCompletionTransportError as exc:
                status = f" (HTTP {exc.status})" if exc.status else ""
                raise AgentExecutionError(
                    f"{provider} implementation provider request failed{status}",
                    {"provider": provider, "http_status": exc.status, "retryable": exc.retryable},
                ) from exc
        url, key = self._endpoint(provider)
        session = requests.Session()
        retry = Retry(
            total=2,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"POST"}),
            respect_retry_after_header=True,
        )
        session.mount("https://", HTTPAdapter(max_retries=retry))
        try:
            response = session.post(
                url,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {key}",
                },
                json=payload,
                timeout=self.timeout,
                allow_redirects=False,
            )
            response.raise_for_status()
            return response.json()
        except requests.Timeout as exc:
            raise AgentExecutionError(
                f"{provider} implementation provider timed out",
                {"provider": provider, "retryable": True, "retry_policy": "2 retries"},
            ) from exc
        except requests.RequestException as exc:
            status = getattr(exc.response, "status_code", None)
            suffix = f" (HTTP {status})" if status else ""
            raise AgentExecutionError(
                f"{provider} implementation provider request failed{suffix}",
                {"provider": provider, "http_status": status, "retryable": status in {429, 500, 502, 503, 504}},
            ) from exc
        except ValueError as exc:
            raise AgentExecutionError(
                f"{provider} implementation provider returned invalid JSON"
            ) from exc

    def _endpoint(self, provider: str) -> tuple[str, str]:
        if provider == "heroku":
            base_url = self.config.get("HEROKU_INFERENCE_BASE_URL")
            key = self.config.get("HEROKU_INFERENCE_KEY")
            if not base_url or not key:
                raise AgentExecutionError(
                    "Heroku implementation requires HEROKU_INFERENCE_BASE_URL and "
                    "HEROKU_INFERENCE_KEY"
                )
            url = f"{base_url.rstrip('/')}/v1/chat/completions"
            _require_https_endpoint(url, "Heroku")
            return url, key
        if provider == "openai_compatible":
            base_url = self.config.get("OPENAI_COMPATIBLE_BASE_URL")
            key = self.config.get("OPENAI_COMPATIBLE_API_KEY")
            if not base_url or not key:
                raise AgentExecutionError(
                    "OpenAI-compatible implementation requires OPENAI_COMPATIBLE_BASE_URL and "
                    "OPENAI_COMPATIBLE_API_KEY"
                )
            _require_https_endpoint(base_url, "OpenAI-compatible")
            return base_url, key
        key = self.config.get("RUNPOD_API_KEY")
        endpoint_id = self.config.get("RUNPOD_ENDPOINT_ID")
        if not key or not endpoint_id:
            raise AgentExecutionError(
                "RunPod implementation requires RUNPOD_API_KEY and RUNPOD_ENDPOINT_ID"
            )
        url = self.config.get("RUNPOD_INFERENCE_URL") or (
            f"https://api.runpod.ai/v2/{endpoint_id}/runsync"
        )
        _require_https_endpoint(url, "RunPod")
        return url, key

    def _payload(self, provider: str, prompt: str) -> dict:
        model = self.model_config.get("model") or self.config.get("AGENT_IMPLEMENTATION_MODEL")
        if provider in {"heroku", "openai_compatible"}:
            if not model:
                model = self.config.get(
                    "OPENAI_COMPATIBLE_MODEL" if provider == "openai_compatible" else "HEROKU_INFERENCE_MODEL"
                )
            if not model:
                raise AgentExecutionError(f"{provider} implementation requires an inference model")
            return {
                "model": model,
                "temperature": 0,
                "max_tokens": self.max_tokens,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": _implementation_system_prompt()},
                    {"role": "user", "content": prompt},
                ],
            }
        return {
            "input": {
                "system_prompt": _implementation_system_prompt(),
                "prompt": prompt,
                "temperature": 0,
                "response_format": {"type": "json_object"},
            }
        }


def parse_execution_result(payload: dict) -> ExecutionResult:
    """Unwrap provider-specific envelopes and validate model output."""
    document = (
        payload.get("output") if isinstance(payload, dict) and "output" in payload else payload
    )
    if isinstance(document, dict) and "choices" in document:
        try:
            document = document["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AgentExecutionError("Provider response has no chat completion content") from exc
    if isinstance(document, dict) and "result" in document:
        document = document["result"]
    if isinstance(document, str):
        document = _strip_json_code_fence(document)
        try:
            document = json.loads(document)
        except json.JSONDecodeError as exc:
            raise AgentExecutionError("Provider output was not a JSON change-set document") from exc
    if not isinstance(document, dict):
        raise AgentExecutionError("Provider output must be a JSON object")

    raw_changes = document.get("changes")
    if not isinstance(raw_changes, list) or not raw_changes:
        raise AgentExecutionError("Provider output must contain a non-empty changes array")
    changes = []
    for raw in raw_changes:
        if not isinstance(raw, dict):
            raise AgentExecutionError("Provider change must be an object")
        path = raw.get("path")
        action = raw.get("action", "modify")
        diff = raw.get("diff")
        if not isinstance(path, str) or not path.strip():
            raise AgentExecutionError("Provider change path must be a non-empty string")
        normalized_path = posixpath.normpath(path.replace("\\", "/"))
        if normalized_path in {".", ".."} or normalized_path.startswith(("../", "/", "~")):
            raise AgentExecutionError("Provider change path must remain inside the workspace")
        if action not in {"add", "modify", "delete"}:
            raise AgentExecutionError("Provider change action must be add, modify or delete")
        if not isinstance(diff, str) or not diff:
            raise AgentExecutionError("Provider change diff must be a non-empty string")
        changes.append(GeneratedChange(path=normalized_path, action=action, diff=diff))

    review = document.get("self_review")
    # Some OpenAI-compatible managed endpoints serialize a JSON-schema field
    # declared as prose as a bare string.  Preserve that provider-authored
    # review verbatim while normalizing it to botq's persisted contract.  A
    # missing, empty, or otherwise malformed review remains a hard failure.
    if isinstance(review, str):
        review = {"result": review}
    if not isinstance(review, dict) or not isinstance(review.get("result"), str) or not review["result"].strip():
        raise AgentExecutionError("Provider output must contain self_review.result")
    evidence = document.get("evidence", {})
    # Evidence is supplemental provider metadata, never verification evidence.
    # Preserve a non-object response under an explicit key so compatible
    # endpoints can complete a draft change-set; only separately recorded,
    # hash-bound verification runs may satisfy a gate.
    if evidence is None:
        evidence = {}
    elif not isinstance(evidence, dict):
        evidence = {"provider_evidence": evidence}
    return ExecutionResult(
        provider="provider",
        changes=changes,
        self_review=review,
        evidence=evidence,
    )


def _strip_json_code_fence(document: str) -> str:
    """Normalize a chat-model JSON fence while retaining strict parsing."""
    value = document.strip()
    lines = value.splitlines()
    if len(lines) < 2 or lines[0].strip().lower() not in {"```", "```json"}:
        return value
    end = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
    return "\n".join(lines[1:end]).strip()


def _implementation_prompt(run, plan: dict, checkpoint: dict | None) -> str:
    runtime = run.environment if isinstance(run.environment, dict) else {}
    public_runtime = {
        key: runtime[key]
        for key in ("branch", "base_commit", "repository_snapshot")
        if key in runtime
    }
    document = {
        "objective": run.objective,
        "plan": plan,
        "runtime_context": public_runtime,
        "resume_checkpoint": checkpoint or {},
        "writable_paths": run.writable_paths,
        "allowed_tools": run.allowed_tools,
    }
    return json.dumps(document, sort_keys=True)


def _implementation_system_prompt() -> str:
    return (
        "You are a bounded software delivery agent. Return JSON only with changes, self_review, "
        "and evidence. Each change must contain path, action (add/modify/delete), and a unified "
        "diff string. Only use paths in the supplied writable_paths. self_review must contain a "
        "non-empty result string. Unified-diff context lines must be copied exactly from the supplied "
        "repository snapshot; never abbreviate them. Do not claim tests passed unless evidence includes "
        "their actual command result. Do not include secrets or invent repository facts."
    )


_HUNK = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def validate_diff_against_snapshot(diff: str, path: str, snapshot: str) -> None:
    """Fail closed when a provider diff contradicts an exact supplied file snapshot.

    This intentionally checks context/removal lines only; it is not a replacement
    for applying and testing a change in the repository workspace.
    """
    marker = f"Approved repository snapshot ({path}, exact current content):\n"
    if marker not in snapshot:
        return
    source = snapshot.split(marker, 1)[1].split("\n\nRequested single-file change:", 1)[0]
    lines = source.splitlines()
    current = None
    saw_hunk = False
    for line in diff.splitlines():
        if line.startswith(("--- ", "+++ ")):
            continue
        match = _HUNK.match(line)
        if match:
            current = int(match.group(1)) - 1
            saw_hunk = True
            continue
        if not saw_hunk or line.startswith("\\ No newline"):
            continue
        if line.startswith((" ", "-")):
            if current is None or current >= len(lines) or lines[current] != line[1:]:
                raise AgentExecutionError(
                    f"Provider diff does not apply to supplied snapshot for {path}"
                )
            current += 1
        elif line.startswith("+"):
            continue
        else:
            raise AgentExecutionError(f"Provider diff is not a valid unified diff for {path}")
    if not saw_hunk:
        raise AgentExecutionError(f"Provider diff has no unified hunk for {path}")


def _require_https_endpoint(url: str, provider: str) -> None:
    try:
        validate_external_https_url(url, f"{provider} inference URL")
    except ValueError as exc:
        raise AgentExecutionError(str(exc)) from exc
