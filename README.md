# botq

botq is a human-supervised AI software-delivery control plane. It connects requirements,
architecture, planning, reviewable agent changes, acceptance, releases, deployments, gates, and
audit evidence while keeping authorization and approval decisions authoritative in the backend.

The repository-side implementation is substantially exercised locally. Production readiness still
requires target-environment evidence, real provider credentials, and named human or policy-selected
automation decisions.

## Architecture

```text
Browser :8884
  ├── React/Vite SPA       -> Nginx frontend
  ├── /api, /health        -> Flask API -> PostgreSQL
  └── /openapi.json        -> Flask API
```

Docker Compose services are `frontend`, `proxy`, `api`, `worker`, `db`, and the restricted
`docker-socket-proxy`. The API and worker share PostgreSQL, Git-key, and sandbox workspace volumes.
The browser uses one origin; authentication tokens are not stored in browser-readable persistence.

## Quick start

Prerequisites: Docker Desktop or Docker Engine with Compose v2, Git, and PowerShell for the
repository helper scripts on Windows.

Create the ignored local environment file from the complete template:

```bash
cp backend/.env.example backend/.env
```

Set strong local values for `SECRET_KEY`, `AUDIT_SECRET`, and `SECRET_ENCRYPTION_KEY`, then start
the stack:

```bash
export POSTGRES_PASSWORD='replace-with-a-long-random-password'
docker compose up -d --build
docker compose exec api flask db upgrade
docker compose exec api flask bootstrap \
  --org-name "Acme" --slug "acme" \
  --email "admin@acme.local" --password "ChangeMe123!"
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

Open the SPA at <http://localhost:8884>. Health endpoints are `/health/live` and `/health/ready`;
the API contract is available at `/openapi.json` and interactive API documentation at `/docs`.
Never use the example credentials or development secrets in production.

For production-like Compose deployment, inject the required secrets and provider settings through
the deployment environment and apply the production overlay:

```bash
docker compose -f docker-compose.yml -f docker-compose.production.yml up -d --build
```

The production overlay disables bootstrap, requires OIDC and Redis-backed rate limiting, removes
the published PostgreSQL port, clears the local `.env` file from service configuration, and uses
restart policies plus health-gated proxy startup. TLS should terminate at the approved ingress or
load balancer in front of Nginx.

## Configuration

`backend/.env.example` is the authoritative non-secret manifest. The ignored `backend/.env` is
kept synchronized with it using safe development defaults. Optional OIDC, Heroku, RunPod, Penpot,
preview, deployment, Redis, and external-provider values remain blank until explicitly configured.

Important groups include:

| Area | Variables |
| --- | --- |
| Security and auth | `ENVIRONMENT`, `SECRET_KEY`, `AUDIT_SECRET`, `SECRET_ENCRYPTION_KEY`, `LOCAL_AUTH_ENABLED`, `OIDC_*`, `BOOTSTRAP_TOKEN` |
| Analysis and agent worker | `REQUIREMENT_ANALYSIS_*`, `AGENT_IMPLEMENTATION_*`, `HEROKU_*`, `RUNPOD_*` |
| Design and deployment | `PENPOT_*`, `PREVIEW_DEPLOYMENT_*`, `DEPLOYMENT_*`, `LOCAL_COMPOSE_*` |
| Operations | `RATE_LIMIT_*`, `REDIS_URL`, `RETENTION_*`, `SANDBOX_*` |

Validate configuration without exposing secrets:

```bash
PYTHONPATH=backend python scripts/validate_provider_config.py --json
PYTHONPATH=backend python scripts/validate_security_baseline.py --json
```

For production, inject secrets through the platform or an external secret manager. Do not commit
`.env` files, provider credentials, private keys, or secret values into source, logs, prompts, or
API payloads.

## API and frontend

The Flask API is organized by domain: authentication, organizations, projects, requirements,
work items, architecture, planning, design, approvals, traceability, Git, secrets, sandbox,
releases, gates, audit, diagnostics, retention, health, and metrics. Backend authorization remains
the security boundary for every protected action.

The React frontend uses Material UI, generated OpenAPI TypeScript contracts, generated Orval
TanStack Query hooks, centralized cookie/CSRF API handling, route guards, and same-origin Nginx
delivery. See [frontend route coverage](docs/FRONTEND_ROUTE_COVERAGE.md).

## Verification

Backend local checks:

```bash
cd backend
PYTHONPATH=. python -m pytest
ruff check .
python -m compileall -q app
```

Frontend checks:

```bash
cd frontend
npm ci
npm run generate:api
npm run generate:hooks
npm run typecheck
npm run lint
npm test
npm run audit
npm run build
```

Run the complete database/API/proxy/SPA/browser workflow from the repository root:

```powershell
./scripts/run_e2e.ps1
```

The current verified Docker run includes 11 backend E2E scenarios, one intentional external-provider
skip without credentials, 27 Playwright tests, axe checks on major screens, clean frontend dependency
installation, and production-like image builds. External provider mutation tests remain opt-in.

## Documentation

- [API and gate control guide](docs/API_GATE_CONTROL_GUIDE.md)
- [E2E and integration testing](docs/E2E_TESTING.md)
- [Frontend route coverage](docs/FRONTEND_ROUTE_COVERAGE.md)
- [Phase 6 operations](docs/PHASE6_OPERATIONS.md)
- [Software-delivery platform requirements](docs/AI_Software_Delivery_Platform_SRS.docx)

The full plan is intentionally represented by these current runbooks and status documents rather
than duplicated phase snapshots. See `ops/` for Prometheus and alerting assets and `scripts/` for
validation, evidence, recovery, and Docker E2E helpers.
