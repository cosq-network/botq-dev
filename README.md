# botq

botq is a human-supervised AI software delivery control plane. It helps teams move from
requirements to architecture, implementation, acceptance, release, and deployment while keeping
authorization, approvals, evidence, and audit history attached to the work.

The platform is designed for delivery workflows where AI can analyze and propose changes, but
people or explicitly authorized automation principals remain responsible for approving scope,
generated changes, releases, and operational gates.

> **Project status:** The repository-side control plane is substantially implemented and locally
> exercised. The pilot is not automatically production-ready: several gates still require valid
> submitted evidence and target-environment validation. See [Pilot status](docs/PILOT_STATUS.md).

## What botq provides

- Multi-tenant organizations, users, projects, roles, scopes, and project responsibilities.
- Local bearer-token authentication with optional OIDC support.
- Versioned requirements, immutable content hashes, analysis findings, and work-item traceability.
- Architecture packages, ADRs, technical plans, and approval-bound revisions.
- Durable agent runs with leases, checkpoints, pause/cancel controls, scoped tools, and writable paths.
- Reviewable change sets with self-review, verification evidence, and approval gates.
- Design references, protected previews, human acceptance testing, and defect tracking.
- SSH Git repository connections with deploy keys, host-key pinning, rotation, revocation, clone, and sync.
- Encrypted secrets with masking, redaction, and prompt-injection policy checks.
- Docker-backed sandbox execution with image/network allowlists and resource limits.
- Release readiness, immutable packages, deployment plans, health checks, and rollback records.
- A seven-gate API for evidence, evaluation, decisions, closure, reopening, and history.
- Append-only, HMAC-chained audit events, diagnostics, metrics, retention, backup, and recovery tooling.

## Delivery lifecycle

```text
Requirements
    ↓
Analysis and work items
    ↓
Architecture and ADRs
    ↓
Technical plan
    ↓
Bounded agent run
    ↓
Reviewable change set and verification
    ↓
Preview, acceptance, and defect resolution
    ↓
Release and deployment plan
    ↓
Deployment, rollback, and operations evidence
    ↓
Seven-gate closure
```

Generated implementation output is never treated as approved production code automatically. The
worker persists a reviewable change set; verification and approval remain separate control points.

## Architecture

The application is a Flask API backed by PostgreSQL. Nginx provides the local HTTP entry point.
The API and worker share the database, Git-key volume, and sandbox workspace volume.

| Component | Responsibility |
| --- | --- |
| `api` | Flask application served by Gunicorn; sandbox Docker calls use a restricted internal proxy |
| `worker` | Durable sandbox/agent-run polling and execution |
| `db` | PostgreSQL 15 persistence |
| `proxy` | Nginx reverse proxy on host port `8884` |
| `docker-socket-proxy` | Restricted Docker API used by the API sandbox endpoints |
| `git-fixture` | Optional real SSH Git remote for validation |

The default Compose network is internal. Only the Nginx proxy publishes a host port. The API does
not mount the host Docker socket directly; its sandbox calls go through the internal
`docker-socket-proxy`. The worker retains the raw socket as the trusted execution boundary.

### Repository layout

```text
backend/
  app/
    auth/             Authentication, tokens, roles, and providers
    orgs/             Organization and user management
    projects/         Project CRUD and responsibilities
    requirements/     Baselines, versions, analysis, and findings
    work_items/       Hierarchy, dependencies, and traceability
    architecture/     Architecture packages, ADRs, and comments
    planning/         Plans, agent runs, checkpoints, and change sets
    design/           Mockups, previews, acceptance, and defects
    approvals/        Generic immutable approval records
    traceability/     Links and cross-artifact search
    git/              SSH repository adapter and routes
    secrets/          Encryption, masking, and secret policy
    sandbox/          Readiness, diagnostics, and Docker execution
    release/          Release, deployment, and rollback controls
    gates/            Seven-gate policy and evidence lifecycle
    audit/            HMAC audit-chain service and routes
    backup/           Backup/restore service and CLI
    templates/        Landing page and acceptance workbench
    static/           Frontend assets
  migrations/         Alembic migrations
  tests/              Backend unit and API tests
  Dockerfile          Production-like API/worker image
e2e/                  Dockerized HTTP end-to-end tests
docs/                 Runbooks, roadmap, pilot status, and requirements
ops/                  Prometheus and alerting assets
scripts/              Validation, pilot, evidence, and operations tooling
nginx/                Reverse-proxy configuration
```

## Quick start with Docker Compose

### Prerequisites

- Docker Desktop or Docker Engine with Compose v2
- Git
- PowerShell for the repository's `.ps1` helpers on Windows

### Start the stack

From the repository root:

```bash
cp backend/.env.example backend/.env
```

Set strong values for `SECRET_KEY`, `AUDIT_SECRET`, and `SECRET_ENCRYPTION_KEY` in
`backend/.env`. Then set the PostgreSQL password in the shell and start the services:

```bash
export POSTGRES_PASSWORD='replace-with-a-long-random-password'
docker compose up -d --build
docker compose exec api flask db upgrade
docker compose exec api flask bootstrap \
  --org-name "Acme" \
  --slug "acme" \
  --email "admin@acme.local" \
  --password "ChangeMe123!"
```

PowerShell:

```powershell
Copy-Item backend/.env.example backend/.env
$env:POSTGRES_PASSWORD = "replace-with-a-long-random-password"
docker compose up -d --build
docker compose exec api flask db upgrade
docker compose exec api flask bootstrap --org-name "Acme" --slug "acme" `
  --email "admin@acme.local" --password "ChangeMe123!"
```

Check the service:

```bash
curl http://localhost:8884/health/live
curl http://localhost:8884/health/ready
curl http://localhost:8884/api/v1/auth/providers
```

The bootstrap command is intended for initial setup. Do not use default secrets or bootstrap
credentials in production.

### Log in

```bash
TOKEN=$(curl -sS -X POST http://localhost:8884/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"organization":"acme","email":"admin@acme.local","password":"ChangeMe123!"}' \
  | python -c 'import json,sys; print(json.load(sys.stdin)["data"]["token"])')

curl -sS http://localhost:8884/api/v1/auth/me \
  -H "Authorization: Bearer $TOKEN"
```

The main API is under `/api/v1`. The operator acceptance workbench is available at
`http://localhost:8884/workbench`.

Interactive API documentation is available at `http://localhost:8884/docs`, with the generated
OpenAPI contract at `http://localhost:8884/openapi.json`. Swagger UI supports the bearer-token
authorization scheme used by the API. JSON request bodies are validated through typed Pydantic
DTOs before controller execution, and the generated schemas are referenced by the OpenAPI
operations.

## API domains

All API routes require an organization-scoped bearer token unless explicitly listed as public.

| Domain | Base routes | Purpose |
| --- | --- | --- |
| Health | `/health/*` | Liveness, readiness, metrics, and Prometheus output |
| Auth | `/api/v1/auth` | Local login/logout, OIDC, current user, providers |
| Organizations | `/api/v1/organizations` | Tenant, user, role, and policy management |
| Projects | `/api/v1/projects` | Project lifecycle and responsibility assignments |
| Requirements | `/api/v1/requirements` | Baselines, versions, analysis, findings, approvals |
| Work items | `/api/v1/work-items` | Epic/feature/story/task/test hierarchy and dependencies |
| Architecture | `/api/v1/architecture` | Architecture packages, ADRs, comments, review |
| Planning | `/api/v1/plans`, `/api/v1/agent-runs` | Plans, runs, checkpoints, change sets, verification |
| Design | `/api/v1/design` | Mockups, Penpot references, previews, HAT, defects |
| Approvals | `/api/v1/approvals` | Generic version/hash-bound approval records |
| Traceability | `/api/v1/traceability` | Links and cross-artifact search |
| Git | `/api/v1/projects/{id}/repository` | Repository connection and synchronization |
| Secrets | `/api/v1/secrets` | Encrypted secret lifecycle and verification |
| Sandbox | `/api/v1/sandbox` | Readiness, runs, diagnostics, and probes |
| Releases | `/api/v1/releases`, `/api/v1/deployment-plans`, `/api/v1/deployments` | Release and deployment controls |
| Gates | `/api/v1/projects/{id}/gates` | Evidence, decisions, closure, reopening, history |
| Audit | `/api/v1/audit` | Tenant-scoped events, chain verification, export |

Every state-changing path is intended to validate authorization, tenant scope, lifecycle state,
content/hash bindings, and audit requirements before committing changes.

## Seven-gate control model

| Gate | Focus |
| --- | --- |
| 1 | Secure setup, repository onboarding, sandbox, and audit integrity |
| 2 | Requirements baseline, findings, work items, and approval |
| 3 | Architecture, technical plan, traceability, and security controls |
| 4 | Managed inference, agent run, change set, verification, and approval |
| 5 | Design, preview, accessibility, acceptance, and defects |
| 6 | Release readiness, package, deployment, health, and rollback |
| 7 | Security, performance, recovery, monitoring, retention, and operations |

Gate policy supports `human_api`, `api_automation`, and `disabled` approval modes. The default
policy is conservative: decisions are required, previous gates must be closed in sequence, and
waivers require an explicit reason and expiry. Missing or failed evidence remains blocking.

The complete API-first workflow is documented in
[API_GATE_CONTROL_GUIDE.md](docs/API_GATE_CONTROL_GUIDE.md).

## Configuration

Configuration is read from environment variables and, for local development, `backend/.env`.
Use [backend/.env.example](backend/.env.example) as the reference template. Important settings
include:

| Area | Variables |
| --- | --- |
| Database | `DATABASE_URL`, `POSTGRES_PASSWORD` |
| Application security | `SECRET_KEY`, `AUDIT_SECRET`, `SECRET_ENCRYPTION_KEY`, `ENVIRONMENT` |
| Authentication | `LOCAL_AUTH_ENABLED`, `OIDC_ENABLED`, `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, `BOOTSTRAP_TOKEN` |
| Git | `GIT_KEY_DIR`, `GIT_KNOWN_HOSTS`, `GIT_SSH_CONNECT_TIMEOUT` |
| Sandbox | `SANDBOX_IMAGES_ALLOWLIST`, `SANDBOX_NETWORK_ALLOWLIST`, resource-limit variables |
| Analysis | `REQUIREMENT_ANALYSIS_PROVIDER`, Heroku or RunPod credentials and model settings |
| Agent worker | `AGENT_IMPLEMENTATION_PROVIDER`, model, timeout, lease, and poll settings |
| Design/preview | `PENPOT_*`, `PREVIEW_DEPLOYMENT_*` |
| Deployment | `DEPLOYMENT_*`, `DEPLOYMENT_ADAPTER`, `LOCAL_COMPOSE_*` |
| Operations | `RATE_LIMIT_*`, `REDIS_URL`, retention settings |

Supported analysis providers include the deterministic `rules` provider and optional Heroku or
RunPod providers. Provider credentials are loaded from the environment and are not returned by the
API. The implementation worker is disabled by default until explicitly configured. Sandbox
networking defaults to `none`; host networking requires explicit configuration and is rejected in
production. Production also requires a dedicated Fernet encryption key, Redis-backed
rate limiting, and a separate bootstrap token when bootstrap is enabled.

## Development

Install the backend dependencies in a virtual environment:

```bash
python -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements-dev.txt
```

PowerShell:

```powershell
py -m venv backend/.venv
backend/.venv/Scripts/python.exe -m pip install -r backend/requirements-dev.txt
```

Run the Flask application locally after PostgreSQL is available and `DATABASE_URL` is configured:

```bash
cd backend
PYTHONPATH=. python wsgi.py
```

For local tests, the test fixture uses an isolated in-memory SQLite database and replaces external
providers/Git execution with deterministic fakes where appropriate:

```bash
cd backend
PYTHONPATH=. python -m pytest
ruff check .
python -m compileall -q app
```

The GitHub Actions workflow runs linting, security checks, dependency scanning, backend tests, and
the Dockerized E2E suite. Its backend job sets an explicit `PYTHONPATH` because the application
package lives under `backend/`.

## End-to-end testing

The E2E suite exercises the deployed API through Nginx and PostgreSQL rather than Flask's test
client. It builds isolated containers, applies migrations, seeds test identities, waits for
readiness, runs the HTTP tests, and cleans up its Compose project and volumes.

From the repository root:

```powershell
./scripts/run_e2e.ps1
```

Useful overrides include `BOTQ_E2E_PORT` and `BOTQ_E2E_BASE_URL`. The E2E Compose configuration
forces rules-based analysis and disables managed implementation providers, so normal E2E runs do
not call Heroku, RunPod, Penpot, or deployment webhooks.

External provider success and real SSH success are opt-in validations:

```powershell
./scripts/validate_git.ps1 -ProjectKey pilotlive
```

The real SSH fixture is available only with the `git-validation` Compose profile.

## Operations and evidence

Useful repository tools include:

```text
scripts/benchmark_api.py                  Live API latency benchmark
scripts/collect_release_evidence.py       Release manifest, checksums, and SBOM inputs
scripts/exercise_local_compose_deployment.py  Local deploy/rollback exercise
scripts/exercise_retention.py             Retention dry-run/execution exercise
scripts/validate_accessibility.py         Accessibility baseline
scripts/validate_provider_config.py       Provider and deployment configuration preflight
scripts/validate_recovery.py              Backup compatibility/recovery validation
scripts/validate_security_baseline.py     Security configuration baseline
scripts/test_alert_rules.py               Prometheus alert-rule validation
scripts/verify_redis_rate_limit.py        Shared rate-limit validation
```

Operational endpoints:

```text
GET /health/live
GET /health/ready
GET /health/metrics
GET /health/metrics/prometheus
GET /api/v1/diagnostics/bundle
GET /api/v1/diagnostics/retention-plan
POST /api/v1/diagnostics/retention/execute
```

Do not place tokens, provider keys, deploy keys, passwords, or secret values in Git, prompts,
evidence, logs, or issue reports. Local evidence is normally kept under the ignored
`.pilot-evidence/` directory.

## Backup and migrations

Apply schema migrations with Flask-Migrate:

```bash
docker compose exec api flask db upgrade
```

The backup CLI is registered with Flask. See the backup service and operations runbooks before
performing a restore. Restore operations verify checksums and refuse to overwrite non-empty targets
unless explicitly configured for replacement.

## Current pilot status

The current pilot profile uses:

- A Flask/PostgreSQL pilot application
- Local Docker Compose preview and deployment
- Heroku managed inference as the selected external inference path
- API automation as the selected gate-decision mode

The repository contains local evidence for many control-plane and hardening exercises, but the
remaining pilot work includes a valid managed-inference change set, hash-bound tests/scans and
reproducibility evidence, submitted release/gate evidence, production-scale operational checks,
live alert delivery, and final Security/Operations decisions.

Do not describe the platform as production-ready until the required evidence has been submitted and
the relevant gates have been closed through the API. See:

- [Pilot status](docs/PILOT_STATUS.md)
- [Pilot execution guide](docs/PILOT_EXECUTION_GUIDE.md)
- [Implementation roadmap](docs/IMPLEMENTATION_ROADMAP.md)
- [Phase 6 operations](docs/PHASE6_OPERATIONS.md)
- [Phase 5 release and deployment](docs/PHASE5_RELEASE_DEPLOYMENT.md)
- [Phase 4 acceptance](docs/PHASE4_ACCEPTANCE.md)
- [Dockerized E2E testing](docs/E2E_TESTING.md)

## License

No license file is currently included in this repository. Add the intended license before
publishing the project for reuse.
