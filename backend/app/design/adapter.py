"""Small Penpot read adapter with an explicit human-handoff fallback.

Penpot deployments expose different API versions and may not grant write
capabilities. The control plane therefore stores only references and calls a
configured, read-only endpoint when explicitly requested. It never pretends
to have edited a Penpot file.
"""

from __future__ import annotations

import requests


class PenpotAdapter:
    provider = "penpot"

    def __init__(self, config):
        self.base_url = (config.get("PENPOT_API_BASE_URL") or "").rstrip("/")
        self.api_token = config.get("PENPOT_API_TOKEN") or ""
        self.file_path = config.get("PENPOT_FILE_PATH", "/api/files/{file_id}")
        self.timeout = int(config.get("PENPOT_API_TIMEOUT_SECONDS", 15))

    @property
    def capabilities(self) -> dict:
        return {
            "read_reference": bool(self.base_url and self.api_token),
            "retrieve_preview": bool(self.base_url and self.api_token),
            "write_file": False,
            "comments": False,
        }

    def handoff(self, file_id: str, file_url: str | None) -> dict:
        return {
            "required": True,
            "reason": "Penpot write/comment capabilities are not simulated by botq",
            "steps": [
                "Open the linked Penpot file",
                "Make design or comment changes in Penpot",
                "Paste the updated file/page/node reference into botq",
                "Submit a new mockup version for review",
            ],
            "file_id": file_id,
            "file_url": file_url,
        }

    def retrieve(self, file_id: str) -> dict:
        if not self.base_url or not self.api_token:
            return {
                "available": False,
                "reason": "PENPOT_API_BASE_URL and PENPOT_API_TOKEN are not configured",
                "handoff_required": True,
            }
        path = self.file_path.format(file_id=file_id)
        try:
            response = requests.get(
                f"{self.base_url}/{path.lstrip('/')}",
                headers={"Accept": "application/json", "Authorization": f"Bearer {self.api_token}"},
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.Timeout as exc:
            return {"available": False, "reason": "Penpot request timed out", "error": str(exc)}
        except requests.RequestException as exc:
            status = getattr(exc.response, "status_code", None)
            suffix = f" (HTTP {status})" if status else ""
            return {"available": False, "reason": f"Penpot request failed{suffix}"}
        except ValueError:
            return {"available": False, "reason": "Penpot returned invalid JSON"}
        return {"available": True, "data": _safe_provider_payload(payload)}


def _safe_provider_payload(payload):
    """Limit provider passthrough to JSON metadata; never expose auth headers."""
    if isinstance(payload, dict):
        return {
            str(key): value
            for key, value in payload.items()
            if key.lower() not in {"token", "secret"}
        }
    return payload
