"""Opt-in provider-boundary checks.

These checks deliberately perform only a safe connectivity probe. Provider
mutation scenarios require a real tenant, credentials, and an agreed test
project, so CI runs them only when an external test URL is explicitly supplied.
"""

import os

import pytest
import requests


@pytest.mark.external
def test_configured_provider_boundary_is_reachable():
    url = os.environ.get("BOTQ_EXTERNAL_PROVIDER_URL")
    if not url:
        pytest.skip("BOTQ_EXTERNAL_PROVIDER_URL is not configured")
    response = requests.get(url, timeout=15, allow_redirects=False)
    assert response.status_code < 500, f"provider boundary returned {response.status_code}"

