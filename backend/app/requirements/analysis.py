"""Requirement decomposition and coverage/consistency analysis.

The provider boundary is deliberately small.  The default provider is a
deterministic rules implementation so local development and CI do not send
requirement content to an external service.  A production Deep Agents adapter
can implement the same ``analyze`` contract and be selected through
``REQUIREMENT_ANALYZER_FACTORY``.
"""

from __future__ import annotations

import hashlib
import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..errors import ApiError, ValidationError

FINDING_CATEGORIES = {"ambiguous", "conflicting", "duplicate", "missing", "untestable"}
SEVERITIES = {"low", "medium", "high", "critical"}

_AMBIGUOUS_TERMS = re.compile(
    r"\b(as needed|etc\.?|appropriate|easy|fast|soon|user[- ]friendly|secure|simple|robust)\b",
    re.IGNORECASE,
)
_NEGATED_REQUIREMENT = re.compile(r"\b(?:must|shall)\s+not\s+(.+)", re.IGNORECASE)
_POSITIVE_REQUIREMENT = re.compile(r"\b(?:must|shall)\s+(.+)", re.IGNORECASE)
_TESTABLE_MARKERS = re.compile(
    r"\b(must|shall|given|when|then|returns?|equals?|within|visible|error|status|can|should)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class FindingProposal:
    category: str
    severity: str
    blocking: bool
    title: str
    description: str
    evidence: dict


@dataclass(frozen=True)
class AnalysisResult:
    findings: list[FindingProposal]
    proposed_work_items: list[dict]


class RequirementAnalyzer(ABC):
    """Provider contract for requirement decomposition."""

    provider = "rules"

    @abstractmethod
    def analyze(self, content: dict) -> AnalysisResult:
        """Analyze a requirement document and return validated findings."""
        ...


class AnalysisProviderError(ApiError):
    def __init__(self, message: str = "Requirement analysis provider failed"):
        super().__init__(message, code="analysis_provider_error", status=502)


class RuleBasedRequirementAnalyzer(RequirementAnalyzer):
    """Conservative baseline analyzer used until the model adapter is configured."""

    def analyze(self, content: dict) -> AnalysisResult:
        findings = _findings(content)
        return AnalysisResult(findings=findings, proposed_work_items=_work_item_proposals(content))


class JsonInferenceAnalyzer(RequirementAnalyzer):
    """Common adapter for providers that return a JSON analysis document."""

    def __init__(
        self,
        *,
        provider: str,
        url: str,
        api_key: str,
        model: str,
        timeout: int,
        max_tokens: int = 4096,
    ):
        self.provider = provider
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValidationError(f"{provider} inference URL must be an absolute HTTPS URL")
        self.url = url
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.max_tokens = max_tokens

    def analyze(self, content: dict) -> AnalysisResult:
        payload = self._request(content)
        return parse_provider_result(payload)

    def _request(self, content: dict) -> dict:
        session = requests.Session()
        session.mount(
            "https://",
            HTTPAdapter(
                max_retries=Retry(
                    total=2,
                    backoff_factor=0.5,
                    status_forcelist=(429, 500, 502, 503, 504),
                    allowed_methods=frozenset({"POST"}),
                    respect_retry_after_header=True,
                )
            ),
        )
        try:
            response = session.post(
                self.url,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                },
                json=self._payload(content),
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response.json()
        except requests.Timeout as exc:
            raise AnalysisProviderError("Requirement analysis provider timed out") from exc
        except requests.RequestException as exc:
            status = getattr(exc.response, "status_code", None)
            suffix = f" (HTTP {status})" if status else ""
            raise AnalysisProviderError(
                f"Requirement analysis provider request failed{suffix}"
            ) from exc
        except ValueError as exc:
            raise AnalysisProviderError(
                "Requirement analysis provider returned invalid JSON"
            ) from exc

    @abstractmethod
    def _payload(self, content: dict) -> dict:
        """Build the provider-specific request payload."""
        ...


class HerokuInferenceAnalyzer(JsonInferenceAnalyzer):
    """Heroku Managed Inference OpenAI-compatible chat-completions adapter."""

    def __init__(
        self, *, base_url: str, api_key: str, model: str, timeout: int, max_tokens: int = 4096
    ):
        super().__init__(
            provider="heroku",
            url=f"{base_url.rstrip('/')}/v1/chat/completions",
            api_key=api_key,
            model=model,
            timeout=timeout,
            max_tokens=max_tokens,
        )

    def _payload(self, content: dict) -> dict:
        return {
            "model": self.model,
            "temperature": 0,
            "max_tokens": self.max_tokens,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": _analysis_system_prompt()},
                {
                    "role": "user",
                    "content": json.dumps({"requirements": content}, sort_keys=True),
                },
            ],
        }


class RunPodInferenceAnalyzer(JsonInferenceAnalyzer):
    """RunPod Serverless ``runsync`` adapter for a JSON-producing worker."""

    def __init__(self, *, endpoint_id: str, api_key: str, timeout: int, url: str | None = None):
        super().__init__(
            provider="runpod",
            url=url or f"https://api.runpod.ai/v2/{endpoint_id}/runsync",
            api_key=api_key,
            model=endpoint_id,
            timeout=timeout,
        )

    def _payload(self, content: dict) -> dict:
        # The worker contract is intentionally explicit: it receives a prompt
        # and returns the JSON document described by _analysis_system_prompt().
        return {
            "input": {
                "system_prompt": _analysis_system_prompt(),
                "prompt": json.dumps({"requirements": content}, sort_keys=True),
                "temperature": 0,
                "response_format": {"type": "json_object"},
            }
        }


class FallbackRequirementAnalyzer(RequirementAnalyzer):
    """Try configured providers in order, preserving an explicit deployment policy."""

    def __init__(self, analyzers: list[RequirementAnalyzer]):
        self.analyzers = analyzers
        self.provider = "+".join(analyzer.provider for analyzer in analyzers)

    def analyze(self, content: dict) -> AnalysisResult:
        failures = []
        for analyzer in self.analyzers:
            try:
                return analyzer.analyze(content)
            except AnalysisProviderError:
                failures.append(analyzer.provider)
        providers = ", ".join(failures) or "configured providers"
        raise AnalysisProviderError(f"All configured analysis providers failed: {providers}")


def configured_analyzer(config: dict) -> RequirementAnalyzer:
    provider_order = [
        value.strip().lower()
        for value in (config.get("REQUIREMENT_ANALYSIS_PROVIDER") or "rules").split(",")
        if value.strip()
    ]
    timeout = int(config.get("REQUIREMENT_ANALYSIS_TIMEOUT_SECONDS", 120))
    analyzers = []
    for provider in provider_order:
        if provider == "rules":
            analyzers.append(RuleBasedRequirementAnalyzer())
            continue
        if provider == "heroku":
            analyzers.append(_heroku_analyzer(config, timeout))
            continue
        if provider == "runpod":
            analyzers.append(_runpod_analyzer(config, timeout))
            continue
        raise ValidationError(
            "REQUIREMENT_ANALYSIS_PROVIDER entries must be rules, heroku or runpod"
        )
    if not analyzers:
        raise ValidationError("REQUIREMENT_ANALYSIS_PROVIDER must contain at least one provider")
    return analyzers[0] if len(analyzers) == 1 else FallbackRequirementAnalyzer(analyzers)


def _heroku_analyzer(config: dict, timeout: int) -> HerokuInferenceAnalyzer:
    key = config.get("HEROKU_INFERENCE_KEY")
    base_url = config.get("HEROKU_INFERENCE_BASE_URL")
    model = config.get("HEROKU_INFERENCE_MODEL")
    if not key or not base_url or not model:
        raise ValidationError(
            "Heroku analysis requires HEROKU_INFERENCE_KEY, "
            "HEROKU_INFERENCE_BASE_URL and HEROKU_INFERENCE_MODEL"
        )
    return HerokuInferenceAnalyzer(
        base_url=base_url,
        api_key=key,
        model=model,
        timeout=timeout,
        max_tokens=int(config.get("HEROKU_INFERENCE_MAX_TOKENS", 4096)),
    )


def _runpod_analyzer(config: dict, timeout: int) -> RunPodInferenceAnalyzer:
    key = config.get("RUNPOD_API_KEY")
    endpoint_id = config.get("RUNPOD_ENDPOINT_ID")
    if not key or not endpoint_id:
        raise ValidationError("RunPod analysis requires RUNPOD_API_KEY and RUNPOD_ENDPOINT_ID")
    url = config.get("RUNPOD_INFERENCE_URL") or f"https://api.runpod.ai/v2/{endpoint_id}/runsync"
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValidationError("RunPod inference URL must be an absolute HTTPS URL")
    return RunPodInferenceAnalyzer(
        endpoint_id=endpoint_id,
        api_key=key,
        timeout=timeout,
        url=url,
    )


def parse_provider_result(payload: dict) -> AnalysisResult:
    """Unwrap a provider response and reject any schema drift before persistence."""
    document = (
        payload.get("output") if isinstance(payload, dict) and "output" in payload else payload
    )
    if isinstance(document, dict) and "choices" in document:
        try:
            document = document["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AnalysisProviderError("Provider response has no chat completion content") from exc
    if isinstance(document, dict) and "result" in document:
        document = document["result"]
    if isinstance(document, str):
        document = _strip_json_code_fence(document)
        try:
            document = json.loads(document)
        except json.JSONDecodeError as exc:
            raise AnalysisProviderError("Provider output was not a JSON analysis document") from exc
    if not isinstance(document, dict):
        raise AnalysisProviderError("Provider output must be a JSON object")
    if "findings" not in document or "proposed_work_items" not in document:
        raise AnalysisProviderError(
            "Provider output must contain findings and proposed_work_items arrays"
        )
    if not isinstance(document["findings"], list):
        raise AnalysisProviderError("Provider findings must be a list")

    findings = []
    for raw in document["findings"]:
        if not isinstance(raw, dict):
            raise AnalysisProviderError("Provider finding must be an object")
        category = raw.get("category")
        severity = raw.get("severity")
        if category not in FINDING_CATEGORIES or severity not in SEVERITIES:
            raise AnalysisProviderError("Provider returned an invalid finding category or severity")
        if not isinstance(raw.get("title"), str) or not isinstance(raw.get("description"), str):
            raise AnalysisProviderError("Provider finding title and description must be strings")
        if not isinstance(raw.get("evidence", {}), dict):
            raise AnalysisProviderError("Provider finding evidence must be an object")
        findings.append(
            FindingProposal(
                category=category,
                severity=severity,
                blocking=bool(raw.get("blocking", severity in {"high", "critical"})),
                title=raw["title"][:200],
                description=raw["description"],
                evidence=raw.get("evidence", {}),
            )
        )

    proposals = document["proposed_work_items"]
    if not isinstance(proposals, list):
        raise AnalysisProviderError("Provider proposed_work_items must be a list")
    # Some OpenAI-compatible gateways emit provenance references as small JSON
    # objects even when the contract asks for strings. Preserve that provenance
    # in a deterministic canonical representation before the strict validator
    # runs; reject all other shapes rather than silently dropping evidence.
    normalized_proposals = []
    for proposal in proposals:
        if not isinstance(proposal, dict):
            normalized_proposals.append(proposal)
            continue
        normalized = dict(proposal)
        priority = normalized.get("priority")
        if isinstance(priority, str):
            normalized["priority"] = {
                "urgent": "critical",
                "blocker": "critical",
                "normal": "medium",
            }.get(priority.strip().lower(), priority.strip().lower())
        risk = normalized.get("risk")
        if isinstance(risk, str):
            normalized["risk"] = {
                "critical": "high",
                "severe": "high",
                "urgent": "high",
                "normal": "medium",
                "negligible": "low",
            }.get(risk.strip().lower(), risk.strip().lower())
        if "source_refs" in normalized and isinstance(normalized["source_refs"], list):
            refs = []
            for reference in normalized["source_refs"]:
                if isinstance(reference, dict):
                    refs.append(json.dumps(reference, sort_keys=True, separators=(",", ":")))
                else:
                    refs.append(reference)
            normalized["source_refs"] = refs
        normalized_proposals.append(normalized)
    proposals = normalized_proposals
    result = AnalysisResult(findings=findings, proposed_work_items=proposals)
    validate_result(result)
    return result


def _strip_json_code_fence(document: str) -> str:
    """Normalize a common chat-model wrapper without relaxing JSON validation."""
    value = document.strip()
    lines = value.splitlines()
    if not lines:
        return value
    language = lines[0].strip().lower()
    if language not in {"```", "```json"}:
        return value
    if len(lines) < 2:
        return value
    end = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
    return "\n".join(lines[1:end]).strip()


def validate_result(result: AnalysisResult) -> None:
    """Validate results from both built-in and injected providers."""
    if not isinstance(result, AnalysisResult):
        raise AnalysisProviderError("Analysis provider returned an invalid result type")
    for finding in result.findings:
        if (
            not isinstance(finding, FindingProposal)
            or finding.category not in FINDING_CATEGORIES
            or finding.severity not in SEVERITIES
            or not isinstance(finding.blocking, bool)
            or not isinstance(finding.title, str)
            or not isinstance(finding.description, str)
            or not isinstance(finding.evidence, dict)
        ):
            raise AnalysisProviderError("Analysis provider returned an invalid finding")
    _validate_proposals(result.proposed_work_items)


def _validate_proposals(proposals: list) -> None:
    refs = set()
    for proposal in proposals:
        if not isinstance(proposal, dict):
            raise AnalysisProviderError("Provider work-item proposal must be an object")
        required = {"ref", "kind", "title", "description", "acceptance_criteria", "source_refs"}
        if not required.issubset(proposal):
            raise AnalysisProviderError("Provider work-item proposal is missing required fields")
        if not isinstance(proposal["ref"], str) or proposal["ref"] in refs:
            raise AnalysisProviderError("Provider work-item proposal refs must be unique")
        refs.add(proposal["ref"])
        if proposal["kind"] not in {"epic", "feature", "story", "task", "test_case"}:
            raise AnalysisProviderError("Provider returned an invalid work-item kind")
        if not isinstance(proposal["title"], str) or not proposal["title"].strip():
            raise AnalysisProviderError("Provider work-item title must be non-empty")
        if not isinstance(proposal.get("description"), str):
            raise AnalysisProviderError("Provider work-item description must be a string")
        if proposal.get("parent_ref") is not None and not isinstance(proposal["parent_ref"], str):
            raise AnalysisProviderError("Provider parent_ref must be a string or null")
        if proposal.get("priority", "medium") not in {"critical", "high", "medium", "low"}:
            raise AnalysisProviderError("Provider returned an invalid work-item priority")
        if proposal.get("risk", "low") not in {"low", "medium", "high"}:
            raise AnalysisProviderError("Provider returned an invalid work-item risk")
        if not isinstance(proposal["acceptance_criteria"], list) or not all(
            isinstance(value, str) for value in proposal["acceptance_criteria"]
        ):
            raise AnalysisProviderError("Provider acceptance criteria must be strings")
        if not isinstance(proposal["source_refs"], list) or not all(
            isinstance(value, str) for value in proposal["source_refs"]
        ):
            raise AnalysisProviderError("Provider source_refs must be strings")
    for proposal in proposals:
        parent_ref = proposal.get("parent_ref")
        if parent_ref is not None and parent_ref not in refs:
            raise AnalysisProviderError("Provider work-item parent_ref does not exist")


def _analysis_system_prompt() -> str:
    return (
        "Analyze the supplied software requirements. Return JSON only with exactly two top-level "
        "arrays: findings and proposed_work_items. Findings use category one of ambiguous, "
        "conflicting, duplicate, missing, untestable; severity one of low, medium, high, critical; "
        "blocking is boolean; include title, description, and evidence object. Work-item proposals "
        "use ref, parent_ref, kind (epic, feature, story, task, test_case), title, description, "
        "acceptance_criteria array, priority, risk, and source_refs array. Only epics may have "
        "parent_ref null; features must belong to an epic, stories to a feature, and tasks/test "
        "cases to a story or feature. Do not invent repository facts; cite the input field in "
        "source_refs."
    )


def fingerprint(finding: FindingProposal) -> str:
    canonical = json.dumps(
        {
            "category": finding.category,
            "title": finding.title,
            "description": finding.description,
            "evidence": finding.evidence,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def summary(findings: list[FindingProposal]) -> dict:
    by_category = {category: 0 for category in sorted(FINDING_CATEGORIES)}
    by_severity = {severity: 0 for severity in sorted(SEVERITIES)}
    for finding in findings:
        by_category[finding.category] += 1
        by_severity[finding.severity] += 1
    return {
        "finding_count": len(findings),
        "blocking_count": sum(finding.blocking for finding in findings),
        "by_category": by_category,
        "by_severity": by_severity,
        "work_item_proposal_count": 0,
    }


def _findings(content: dict) -> list[FindingProposal]:
    findings: list[FindingProposal] = []

    if not content.get("functional_specifications"):
        findings.append(
            FindingProposal(
                category="missing",
                severity="high",
                blocking=True,
                title="Functional specifications are missing",
                description=(
                    "The baseline has goals but no functional specifications. Add the behavior "
                    "that the implementation must provide before approval."
                ),
                evidence={"field": "functional_specifications", "expected": "one or more entries"},
            )
        )
    if not content.get("acceptance_expectations"):
        findings.append(
            FindingProposal(
                category="missing",
                severity="high",
                blocking=True,
                title="Acceptance expectations are missing",
                description=(
                    "No acceptance expectations were supplied, so the generated work cannot be "
                    "verified objectively. Add testable outcomes."
                ),
                evidence={"field": "acceptance_expectations", "expected": "one or more entries"},
            )
        )

    entries = _text_entries(content)
    seen: dict[str, list[dict]] = {}
    for entry in entries:
        key = _canonical_text(entry["text"])
        seen.setdefault(key, []).append(entry)
        match = _AMBIGUOUS_TERMS.search(entry["text"])
        if match:
            findings.append(
                FindingProposal(
                    category="ambiguous",
                    severity="medium",
                    blocking=False,
                    title="Ambiguous requirement language",
                    description=(
                        f"The term '{match.group(0)}' has no measurable definition in this "
                        "requirement. Replace it with an observable constraint or outcome."
                    ),
                    evidence={
                        "field": entry["field"],
                        "index": entry["index"],
                        "text": entry["text"],
                        "term": match.group(0),
                    },
                )
            )

    for locations in seen.values():
        if len(locations) > 1:
            findings.append(
                FindingProposal(
                    category="duplicate",
                    severity="low",
                    blocking=False,
                    title="Duplicate requirement statement",
                    description="The same statement appears more than once in the baseline.",
                    evidence={"locations": locations},
                )
            )

    findings.extend(_conflicting_findings(entries))
    for entry in content.get("acceptance_expectations") or []:
        if len(entry.split()) < 3 or not _TESTABLE_MARKERS.search(entry):
            findings.append(
                FindingProposal(
                    category="untestable",
                    severity="high",
                    blocking=True,
                    title="Acceptance expectation is not objectively testable",
                    description=(
                        "Add an observable result, condition, threshold, or expected error so "
                        "the expectation can be verified by a test."
                    ),
                    evidence={
                        "field": "acceptance_expectations",
                        "index": (content.get("acceptance_expectations") or []).index(entry),
                        "text": entry,
                    },
                )
            )
    return findings


def _conflicting_findings(entries: list[dict]) -> list[FindingProposal]:
    positive: dict[str, dict] = {}
    negative: dict[str, dict] = {}
    for entry in entries:
        positive_match = _POSITIVE_REQUIREMENT.search(entry["text"])
        negative_match = _NEGATED_REQUIREMENT.search(entry["text"])
        if positive_match and not negative_match:
            positive[_canonical_text(positive_match.group(1))] = entry
        if negative_match:
            negative[_canonical_text(negative_match.group(1))] = entry

    findings = []
    for key in sorted(set(positive) & set(negative)):
        findings.append(
            FindingProposal(
                category="conflicting",
                severity="critical",
                blocking=True,
                title="Conflicting mandatory requirements",
                description="The baseline contains both a mandatory and a mandatory-negative form of the same requirement.",
                evidence={"positive": positive[key], "negative": negative[key]},
            )
        )
    return findings


def _work_item_proposals(content: dict) -> list[dict]:
    """Create reviewable hierarchy proposals without silently writing to the project."""
    proposals: list[dict] = []
    goals = content.get("goals") or ["Requirements delivery"]
    first_epic_ref = None
    for index, goal in enumerate(goals):
        ref = f"epic-{index + 1}"
        first_epic_ref = first_epic_ref or ref
        proposals.append(
            {
                "ref": ref,
                "kind": "epic",
                "parent_ref": None,
                "title": _title(goal, "Goal"),
                "description": goal,
                "acceptance_criteria": [],
                "priority": "high",
                "risk": "medium",
                "source_refs": [f"content.goals[{index}]"],
            }
        )

    specs = content.get("functional_specifications") or []
    feature_parent = first_epic_ref
    for index, specification in enumerate(specs):
        ref = f"feature-{index + 1}"
        proposals.append(
            {
                "ref": ref,
                "kind": "feature",
                "parent_ref": feature_parent,
                "title": _title(specification, "Functional specification"),
                "description": specification,
                "acceptance_criteria": [],
                "priority": "medium",
                "risk": "medium",
                "source_refs": [f"content.functional_specifications[{index}]"],
            }
        )

    acceptance_parent = "feature-1" if specs else first_epic_ref
    for index, expectation in enumerate(content.get("acceptance_expectations") or []):
        ref = f"test-case-{index + 1}"
        proposals.append(
            {
                "ref": ref,
                "kind": "test_case",
                "parent_ref": acceptance_parent,
                "title": _title(expectation, "Acceptance test"),
                "description": expectation,
                "acceptance_criteria": [expectation],
                "priority": "high",
                "risk": "medium",
                "source_refs": [f"content.acceptance_expectations[{index}]"],
            }
        )
    return proposals


def _text_entries(content: dict) -> list[dict]:
    entries = []
    for field in (
        "goals",
        "functional_specifications",
        "constraints",
        "acceptance_expectations",
    ):
        for index, text in enumerate(content.get(field) or []):
            entries.append({"field": field, "index": index, "text": text})
    return entries


def _canonical_text(value: str) -> str:
    return " ".join(value.casefold().split())


def _title(value: str, prefix: str) -> str:
    value = " ".join(value.split())
    return value[:200] if value else prefix
