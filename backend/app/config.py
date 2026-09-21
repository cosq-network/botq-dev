import os
from pathlib import Path

from dotenv import load_dotenv

# Always resolve the local development file relative to ``backend/``.  Calling
# Flask or a validation script from the repository root must not silently omit
# the managed-inference configuration stored in ``backend/.env``.
load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class Config:
    APP_NAME = os.environ.get("APP_NAME", "botq")
    ENVIRONMENT = os.environ.get("ENVIRONMENT", "development")

    SECRET_KEY = os.environ.get("SECRET_KEY", "change-me-in-production")
    BOOTSTRAP_ENABLED = _env_bool("BOOTSTRAP_ENABLED", ENVIRONMENT.lower() != "production")
    BOOTSTRAP_TOKEN = os.environ.get("BOOTSTRAP_TOKEN", "")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        "postgresql+psycopg2://botq:botq@localhost:5432/botq",
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    AUTH_MODE = os.environ.get("AUTH_MODE", "local")
    TOKEN_TTL_SECONDS = int(os.environ.get("TOKEN_TTL_SECONDS", "86400"))
    # Authentication is checked on every request, but token activity only
    # needs periodic persistence. This avoids a database write per request.
    TOKEN_ACTIVITY_UPDATE_SECONDS = int(
        os.environ.get("TOKEN_ACTIVITY_UPDATE_SECONDS", "300")
    )
    LOCAL_AUTH_ENABLED = _env_bool("LOCAL_AUTH_ENABLED", True)
    OIDC_ENABLED = _env_bool("OIDC_ENABLED", False)
    OIDC_ISSUER = os.environ.get("OIDC_ISSUER", "")
    OIDC_CLIENT_ID = os.environ.get("OIDC_CLIENT_ID", "")
    OIDC_CLIENT_SECRET = os.environ.get("OIDC_CLIENT_SECRET", "")
    OIDC_SCOPES = os.environ.get("OIDC_SCOPES", "openid profile email")
    OIDC_SUCCESS_REDIRECT_URI = os.environ.get("OIDC_SUCCESS_REDIRECT_URI", "/")
    SESSION_COOKIE_SECURE = ENVIRONMENT.lower() == "production"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"

    AUDIT_SECRET = os.environ.get("AUDIT_SECRET", "change-me-audit-chain-secret")
    SECRET_ENCRYPTION_KEY = os.environ.get("SECRET_ENCRYPTION_KEY", "")

    GIT_SSH = os.environ.get("GIT_SSH", "ssh")
    GIT_KEY_DIR = os.environ.get("GIT_KEY_DIR", "secrets/git")
    GIT_KNOWN_HOSTS = os.environ.get("GIT_KNOWN_HOSTS", "secrets/git/known_hosts")
    GIT_SSH_CONNECT_TIMEOUT = int(os.environ.get("GIT_SSH_CONNECT_TIMEOUT", "10"))

    SANDBOX_IMAGES_ALLOWLIST = [
        i.strip()
        for i in os.environ.get(
            "SANDBOX_IMAGES_ALLOWLIST",
            "python:3.13-slim,node:22-bookworm,botq/toolchain:latest",
        ).split(",")
        if i.strip()
    ]
    SANDBOX_NETWORK_ALLOWLIST = [
        i.strip()
        for i in os.environ.get("SANDBOX_NETWORK_ALLOWLIST", "none").split(",")
        if i.strip()
    ]
    SANDBOX_ALLOW_HOST_NETWORK = _env_bool("SANDBOX_ALLOW_HOST_NETWORK", False)
    SANDBOX_DEFAULT_LIMITS = {
        "cpu": os.environ.get("SANDBOX_DEFAULT_CPU", "1.0"),
        "memory": os.environ.get("SANDBOX_DEFAULT_MEMORY", "1g"),
        "pids": int(os.environ.get("SANDBOX_DEFAULT_PIDS", "256")),
        "timeout": int(os.environ.get("SANDBOX_DEFAULT_TIMEOUT", "600")),
    }
    SANDBOX_MAX_CPU = float(os.environ.get("SANDBOX_MAX_CPU", "4.0"))
    SANDBOX_MAX_MEMORY_BYTES = int(os.environ.get("SANDBOX_MAX_MEMORY_BYTES", str(4 * 1024**3)))
    SANDBOX_MAX_PIDS = int(os.environ.get("SANDBOX_MAX_PIDS", "1024"))
    SANDBOX_MAX_TIMEOUT = int(os.environ.get("SANDBOX_MAX_TIMEOUT", "3600"))
    SANDBOX_ALLOW_PRIVILEGED = _env_bool("SANDBOX_ALLOW_PRIVILEGED", False)
    SANDBOX_ALLOW_HOST_MOUNTS = _env_bool("SANDBOX_ALLOW_HOST_MOUNTS", False)

    RUNTIME_RUNNER = os.environ.get("RUNTIME_RUNNER", "subprocess")
    AGENT_IMPLEMENTATION_PROVIDER = os.environ.get("AGENT_IMPLEMENTATION_PROVIDER", "disabled")
    AGENT_IMPLEMENTATION_TIMEOUT_SECONDS = int(
        os.environ.get("AGENT_IMPLEMENTATION_TIMEOUT_SECONDS", "180")
    )
    AGENT_WORKER_LEASE_SECONDS = int(os.environ.get("AGENT_WORKER_LEASE_SECONDS", "900"))
    AGENT_WORKER_POLL_SECONDS = int(os.environ.get("AGENT_WORKER_POLL_SECONDS", "30"))
    AGENT_IMPLEMENTATION_MODEL = os.environ.get("AGENT_IMPLEMENTATION_MODEL", "")

    REQUIREMENT_ANALYSIS_PROMPT_VERSION = os.environ.get(
        "REQUIREMENT_ANALYSIS_PROMPT_VERSION", "rules-v1"
    )
    REQUIREMENT_ANALYSIS_POLICY_VERSION = os.environ.get(
        "REQUIREMENT_ANALYSIS_POLICY_VERSION", "baseline-v1"
    )
    REQUIREMENT_ANALYSIS_PROVIDER = os.environ.get("REQUIREMENT_ANALYSIS_PROVIDER", "rules")
    REQUIREMENT_ANALYSIS_TIMEOUT_SECONDS = int(
        os.environ.get("REQUIREMENT_ANALYSIS_TIMEOUT_SECONDS", "120")
    )
    HEROKU_INFERENCE_BASE_URL = os.environ.get("HEROKU_INFERENCE_BASE_URL", "")
    HEROKU_INFERENCE_KEY = os.environ.get("HEROKU_INFERENCE_KEY", "")
    HEROKU_INFERENCE_MODEL = os.environ.get("HEROKU_INFERENCE_MODEL", "")
    HEROKU_INFERENCE_MAX_TOKENS = int(os.environ.get("HEROKU_INFERENCE_MAX_TOKENS", "4096"))
    RUNPOD_API_KEY = os.environ.get("RUNPOD_API_KEY", "")
    RUNPOD_ENDPOINT_ID = os.environ.get("RUNPOD_ENDPOINT_ID", "")
    RUNPOD_INFERENCE_URL = os.environ.get("RUNPOD_INFERENCE_URL", "")

    PENPOT_API_BASE_URL = os.environ.get("PENPOT_API_BASE_URL", "")
    PENPOT_API_TOKEN = os.environ.get("PENPOT_API_TOKEN", "")
    PENPOT_FILE_PATH = os.environ.get("PENPOT_FILE_PATH", "/api/files/{file_id}")
    PENPOT_API_TIMEOUT_SECONDS = int(os.environ.get("PENPOT_API_TIMEOUT_SECONDS", "15"))

    PREVIEW_DEPLOYMENT_URL = os.environ.get("PREVIEW_DEPLOYMENT_URL", "")
    PREVIEW_DEPLOYMENT_TOKEN = os.environ.get("PREVIEW_DEPLOYMENT_TOKEN", "")
    PREVIEW_DEPLOYMENT_TIMEOUT_SECONDS = int(
        os.environ.get("PREVIEW_DEPLOYMENT_TIMEOUT_SECONDS", "120")
    )

    DEPLOYMENT_URL = os.environ.get("DEPLOYMENT_URL", "")
    DEPLOYMENT_ROLLBACK_URL = os.environ.get("DEPLOYMENT_ROLLBACK_URL", "")
    DEPLOYMENT_TOKEN = os.environ.get("DEPLOYMENT_TOKEN", "")
    DEPLOYMENT_TIMEOUT_SECONDS = int(os.environ.get("DEPLOYMENT_TIMEOUT_SECONDS", "180"))
    DEPLOYMENT_ADAPTER = os.environ.get("DEPLOYMENT_ADAPTER", "webhook")
    LOCAL_COMPOSE_FILE = os.environ.get("LOCAL_COMPOSE_FILE", "")
    LOCAL_COMPOSE_ROLLBACK_FILE = os.environ.get("LOCAL_COMPOSE_ROLLBACK_FILE", "")
    LOCAL_COMPOSE_PROJECT = os.environ.get("LOCAL_COMPOSE_PROJECT", "")
    LOCAL_DEPLOYMENT_HEALTH_URL = os.environ.get("LOCAL_DEPLOYMENT_HEALTH_URL", "")
    LOCAL_DEPLOYMENT_HEALTH_TIMEOUT_SECONDS = int(
        os.environ.get("LOCAL_DEPLOYMENT_HEALTH_TIMEOUT_SECONDS", "90")
    )

    RATE_LIMIT_ENABLED = _env_bool("RATE_LIMIT_ENABLED", ENVIRONMENT.lower() == "production")
    RATE_LIMIT_PER_MINUTE = int(os.environ.get("RATE_LIMIT_PER_MINUTE", "120"))
    RATE_LIMIT_BACKEND = os.environ.get("RATE_LIMIT_BACKEND", "memory")
    REDIS_URL = os.environ.get("REDIS_URL", "")
    RETENTION_AUDIT_DAYS = int(os.environ.get("RETENTION_AUDIT_DAYS", "365"))
    RETENTION_AGENT_EVENT_DAYS = int(os.environ.get("RETENTION_AGENT_EVENT_DAYS", "90"))
    RETENTION_CHECKPOINT_DAYS = int(os.environ.get("RETENTION_CHECKPOINT_DAYS", "30"))

    SANDBOX_WORKSPACE_DIR = os.environ.get("SANDBOX_WORKSPACE_DIR", "workspaces")

    JSON_SORT_KEYS = False
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024
