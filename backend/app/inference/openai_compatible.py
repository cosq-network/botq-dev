"""Bounded transport for OpenAI-compatible Chat Completions endpoints."""

from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..security.network import validate_external_https_url


class ChatCompletionTransportError(Exception):
    """A sanitized provider transport failure."""

    def __init__(self, message: str, *, status: int | None = None, retryable: bool = False):
        super().__init__(message)
        self.status = status
        self.retryable = retryable


def chat_completions_url(base_url: str) -> str:
    value = str(base_url).rstrip("/")
    validate_external_https_url(value, "OpenAI-compatible inference URL")
    return f"{value}/v1/chat/completions"


def request_chat_completion(
    *, base_url: str, api_key: str, payload: dict, timeout: int,
    max_response_bytes: int = 2 * 1024 * 1024,
) -> dict:
    """POST a bounded JSON request, retrying only transient HTTP failures."""
    url = chat_completions_url(base_url)
    session = requests.Session()
    session.mount(
        "https://",
        HTTPAdapter(
            max_retries=Retry(
                total=2, backoff_factor=0.5,
                status_forcelist=(429, 500, 502, 503, 504),
                allowed_methods=frozenset({"POST"}),
                respect_retry_after_header=True,
            )
        ),
    )
    try:
        response = session.post(
            url,
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json", "Content-Type": "application/json"},
            json=payload, timeout=timeout, allow_redirects=False,
        )
        status = response.status_code
        if status >= 300:
            raise ChatCompletionTransportError(
                f"OpenAI-compatible provider request failed (HTTP {status})",
                status=status, retryable=status in {429, 500, 502, 503, 504},
            )
        if len(response.content) > max_response_bytes:
            raise ChatCompletionTransportError("OpenAI-compatible provider response was too large")
        try:
            document = response.json()
        except ValueError as exc:
            raise ChatCompletionTransportError("OpenAI-compatible provider returned invalid JSON") from exc
        if not isinstance(document, dict):
            raise ChatCompletionTransportError("OpenAI-compatible provider response must be an object")
        return document
    except ChatCompletionTransportError:
        raise
    except requests.Timeout as exc:
        raise ChatCompletionTransportError("OpenAI-compatible provider timed out", retryable=True) from exc
    except requests.RequestException as exc:
        raise ChatCompletionTransportError("OpenAI-compatible provider request failed", retryable=True) from exc
