"""Provider-neutral deployment boundary for Phase 5.

The control plane owns approval and release policy. A configured deployment
provider owns the actual host operation and must return diagnostics and health
evidence. No deployment is simulated when the provider is unavailable.
"""

from __future__ import annotations

import os
import subprocess  # nosec B404 - local adapter uses fixed docker compose argv.
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..errors import ApiError
from ..security.network import validate_external_https_url


class DeploymentProviderError(ApiError):
    def __init__(self, message: str = "Deployment provider failed"):
        super().__init__(message, code="deployment_provider_failed", status=502)


@dataclass(frozen=True)
class DeploymentResult:
    status: str
    provider_id: str | None
    diagnostics: dict
    health_checks: dict


class DeploymentAdapter(ABC):
    @abstractmethod
    def provision(self, manifest: dict) -> DeploymentResult:
        """Deploy a release and return provider health evidence."""
        ...

    @abstractmethod
    def rollback(self, manifest: dict) -> DeploymentResult:
        """Restore the previous release and return provider health evidence."""
        ...


class WebhookDeploymentAdapter(DeploymentAdapter):
    """Call an approved HTTPS deployment webhook using a strict JSON contract."""

    def __init__(self, config: dict):
        self.url = (config.get("DEPLOYMENT_URL") or "").strip()
        self.rollback_url = (config.get("DEPLOYMENT_ROLLBACK_URL") or self.url).strip()
        self.token = config.get("DEPLOYMENT_TOKEN") or ""
        self.timeout = int(config.get("DEPLOYMENT_TIMEOUT_SECONDS", 180))
        if not self.url or not self.token:
            raise DeploymentProviderError("Deployment requires DEPLOYMENT_URL and DEPLOYMENT_TOKEN")
        for name, value in (
            ("DEPLOYMENT_URL", self.url),
            ("DEPLOYMENT_ROLLBACK_URL", self.rollback_url),
        ):
            try:
                validate_external_https_url(value, name)
            except ValueError as exc:
                raise DeploymentProviderError(str(exc)) from exc
        if self.timeout <= 0 or self.timeout > 3600:
            raise DeploymentProviderError("DEPLOYMENT_TIMEOUT_SECONDS must be between 1 and 3600")

    def provision(self, manifest: dict) -> DeploymentResult:
        payload = {"action": "deploy", **manifest}
        return self._request(self.url, payload)

    def rollback(self, manifest: dict) -> DeploymentResult:
        payload = {"action": "rollback", **manifest}
        return self._request(self.rollback_url, payload)

    def _request(self, url: str, payload: dict) -> DeploymentResult:
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
                url,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.token}",
                },
                json=payload,
                timeout=self.timeout,
                allow_redirects=False,
            )
            response.raise_for_status()
            document = response.json()
        except requests.Timeout as exc:
            raise DeploymentProviderError("Deployment provider timed out") from exc
        except requests.RequestException as exc:
            status = getattr(exc.response, "status_code", None)
            suffix = f" (HTTP {status})" if status else ""
            raise DeploymentProviderError(f"Deployment provider request failed{suffix}") from exc
        except ValueError as exc:
            raise DeploymentProviderError("Deployment provider returned invalid JSON") from exc
        return parse_deployment_result(document)


class LocalComposeDeploymentAdapter(DeploymentAdapter):
    """Explicitly opt-in adapter for controlled local/non-production Compose runs."""

    def __init__(self, config: dict):
        self.compose_files = _compose_files(config.get("LOCAL_COMPOSE_FILE"))
        self.rollback_compose_files = _compose_files(config.get("LOCAL_COMPOSE_ROLLBACK_FILE"))
        self.project = str(config.get("LOCAL_COMPOSE_PROJECT") or "").strip()
        self.health_url = str(config.get("LOCAL_DEPLOYMENT_HEALTH_URL") or "").strip()
        self.health_timeout = int(config.get("LOCAL_DEPLOYMENT_HEALTH_TIMEOUT_SECONDS", 90))
        if not self.compose_files or not self.health_url:
            raise DeploymentProviderError(
                "Local Compose requires LOCAL_COMPOSE_FILE and LOCAL_DEPLOYMENT_HEALTH_URL"
            )
        if urlparse(self.health_url).scheme not in {"http", "https"}:
            raise DeploymentProviderError("LOCAL_DEPLOYMENT_HEALTH_URL must be an absolute HTTP(S) URL")
        if self.health_timeout <= 0 or self.health_timeout > 600:
            raise DeploymentProviderError(
                "LOCAL_DEPLOYMENT_HEALTH_TIMEOUT_SECONDS must be between 1 and 600"
            )

    def provision(self, manifest: dict) -> DeploymentResult:
        return self._run("up", manifest)

    def rollback(self, manifest: dict) -> DeploymentResult:
        rollback = manifest.get("rollback") if isinstance(manifest, dict) else None
        rollback_files = _compose_files(rollback.get("compose_files")) if isinstance(rollback, dict) else []
        rollback_files = rollback_files or self.rollback_compose_files
        if not rollback_files:
            raise DeploymentProviderError(
                "Local Compose rollback requires an explicit previous compose definition"
            )
        return self._run("rollback", manifest, rollback_files)

    def _run(self, action: str, manifest: dict, compose_files: list[str] | None = None) -> DeploymentResult:
        compose_files = compose_files or self.compose_files
        command = ["docker", "compose"]
        for compose_file in compose_files:
            command.extend(["-f", compose_file])
        if self.project:
            command.extend(["-p", self.project])
        command.extend(["up", "-d"])
        try:
            completed = subprocess.run(  # nosec B603 - command is fixed docker compose argv.
                command,
                capture_output=True,
                text=True,
                timeout=300,
                check=True,
            )
            healthy, status_code = self._wait_for_health()
        except (OSError, subprocess.SubprocessError, requests.RequestException) as exc:
            raise DeploymentProviderError(f"Local Compose {action} failed: {type(exc).__name__}") from exc
        return DeploymentResult(
            status="healthy" if healthy else "failed",
            provider_id=f"local-compose:{manifest['deployment_id']}:{action}",
            diagnostics={"command": command, "stdout": completed.stdout[-2000:], "action": action},
            health_checks={"url": self.health_url, "status_code": status_code, "ready": healthy},
        )

    def _wait_for_health(self) -> tuple[bool, int | None]:
        deadline = time.monotonic() + self.health_timeout
        status_code = None
        while time.monotonic() < deadline:
            try:
                response = requests.get(self.health_url, timeout=10)
                status_code = response.status_code
                if response.ok:
                    return True, status_code
            except requests.RequestException:
                status_code = None
            time.sleep(2)
        return False, status_code


def _compose_files(value) -> list[str]:
    if isinstance(value, (list, tuple)):
        candidates = [str(item).strip() for item in value]
    else:
        text = str(value or "").strip()
        if not text:
            return []
        delimiter = "," if "," in text else os.pathsep
        candidates = [item.strip() for item in text.split(delimiter)]
    return [item for item in candidates if item]


def parse_deployment_result(payload: dict) -> DeploymentResult:
    if not isinstance(payload, dict):
        raise DeploymentProviderError("Deployment provider response must be an object")
    status = str(payload.get("status") or "").strip().lower()
    if status not in {"queued", "running", "healthy", "failed", "rolled_back"}:
        raise DeploymentProviderError(
            "Deployment provider response status must be queued, running, healthy, failed, or rolled_back"
        )
    provider_id = payload.get("deployment_id")
    if provider_id is not None and not isinstance(provider_id, str):
        raise DeploymentProviderError("deployment_id must be a string or null")
    diagnostics = payload.get("diagnostics", {})
    health_checks = payload.get("health_checks", {})
    if not isinstance(diagnostics, dict) or not isinstance(health_checks, dict):
        raise DeploymentProviderError("diagnostics and health_checks must be objects")
    return DeploymentResult(
        status=status,
        provider_id=provider_id,
        diagnostics=diagnostics,
        health_checks=health_checks,
    )
