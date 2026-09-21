"""Network destination checks for application-controlled outbound requests."""

from __future__ import annotations

import ipaddress
from urllib.parse import urlparse


def validate_external_https_url(url: str, setting_name: str = "URL") -> None:
    """Reject unsafe destinations before making an application HTTP request.

    DNS resolution is intentionally not performed here: configuration and
    provider adapters are also constructed in offline CI environments. The
    request clients disable redirects, while this check blocks literal local
    and reserved IP destinations and local-only hostnames.
    """
    parsed = urlparse(str(url))
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError(f"{setting_name} must be an absolute HTTPS URL")
    if parsed.username or parsed.password:
        raise ValueError(f"{setting_name} must not contain URL credentials")

    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise ValueError(f"{setting_name} must not target localhost")
    if hostname in {"metadata.google.internal", "metadata"}:
        raise ValueError(f"{setting_name} must not target cloud metadata services")

    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return
    if (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    ):
        raise ValueError(f"{setting_name} must not target a private or reserved IP address")
