"""Preview deployment adapter boundary.

The control plane owns preview policy and immutable bindings. A deployment
provider owns the actual hosting operation and returns an authenticated,
non-production URL. No provider response is trusted until it passes the same
URL/schema checks used by the API.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..errors import ApiError
from ..security.network import validate_external_https_url


class PreviewDeploymentError(ApiError):
    def __init__(self, message: str = "Preview deployment failed"):
        super().__init__(message, code="preview_deployment_failed", status=502)


@dataclass(frozen=True)
class ProvisionedPreview:
    url: str
    deployment_id: str | None
    evidence: dict


class PreviewDeploymentAdapter(ABC):
    @abstractmethod
    def provision(self, manifest: dict) -> ProvisionedPreview:
        """Provision a protected, non-production preview and return its evidence."""
        ...


class WebhookPreviewDeploymentAdapter(PreviewDeploymentAdapter):
    """Call an approved external preview host using a small JSON contract."""

    def __init__(self, config: dict):
        self.url = (config.get("PREVIEW_DEPLOYMENT_URL") or "").strip()
        self.token = config.get("PREVIEW_DEPLOYMENT_TOKEN") or ""
        self.timeout = int(config.get("PREVIEW_DEPLOYMENT_TIMEOUT_SECONDS", 120))
        if not self.url or not self.token:
            raise PreviewDeploymentError(
                "Preview deployment requires PREVIEW_DEPLOYMENT_URL and PREVIEW_DEPLOYMENT_TOKEN"
            )
        try:
            validate_external_https_url(self.url, "PREVIEW_DEPLOYMENT_URL")
        except ValueError as exc:
            raise PreviewDeploymentError(str(exc)) from exc

    def provision(self, manifest: dict) -> ProvisionedPreview:
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
                    "Authorization": f"Bearer {self.token}",
                },
                json=manifest,
                timeout=self.timeout,
                allow_redirects=False,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.Timeout as exc:
            raise PreviewDeploymentError("Preview deployment provider timed out") from exc
        except requests.RequestException as exc:
            status = getattr(exc.response, "status_code", None)
            suffix = f" (HTTP {status})" if status else ""
            raise PreviewDeploymentError(
                f"Preview deployment provider request failed{suffix}"
            ) from exc
        except ValueError as exc:
            raise PreviewDeploymentError(
                "Preview deployment provider returned invalid JSON"
            ) from exc
        return parse_provisioned_preview(payload)


def parse_provisioned_preview(payload: dict) -> ProvisionedPreview:
    if not isinstance(payload, dict):
        raise PreviewDeploymentError("Preview deployment response must be an object")
    url = payload.get("url")
    try:
        validate_external_https_url(str(url or ""), "Preview deployment response URL")
    except ValueError as exc:
        raise PreviewDeploymentError(str(exc)) from exc
    deployment_id = payload.get("deployment_id")
    if deployment_id is not None and not isinstance(deployment_id, str):
        raise PreviewDeploymentError("deployment_id must be a string or null")
    evidence = payload.get("evidence", {})
    if not isinstance(evidence, dict):
        raise PreviewDeploymentError("Preview deployment evidence must be an object")
    return ProvisionedPreview(url=str(url), deployment_id=deployment_id, evidence=evidence)
