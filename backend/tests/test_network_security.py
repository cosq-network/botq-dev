import pytest

from app.security.network import validate_external_https_url


@pytest.mark.parametrize(
    "url",
    [
        "http://provider.example/api",
        "https://user:password@provider.example/api",
        "https://localhost/api",
        "https://127.0.0.1/api",
        "https://10.0.0.5/api",
        "https://169.254.169.254/latest/meta-data",
    ],
)
def test_external_https_url_rejects_unsafe_destinations(url):
    with pytest.raises(ValueError):
        validate_external_https_url(url)


def test_external_https_url_accepts_public_hostname():
    validate_external_https_url("https://provider.example/api")
