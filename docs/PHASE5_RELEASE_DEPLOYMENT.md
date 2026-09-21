# Phase 5 Release and Deployment Runbook

**Status:** Repository-side control plane implemented; the agreed pilot target is local Docker Compose.
The remediated image was built, scanned, deployed locally, rolled back to the immutable base image,
and restored with health `ok`. Gate 6 closure now happens through the explicit gate API and remains
blocked until release/deployment evidence is synchronized or submitted and the selected policy records
its API decisions.

For this pilot, the target application is the Flask/PostgreSQL repository
`git@github.com:cosq-network/botq-dev-pilot-1.git` at commit `31cbdb1`. The local-only preview decision
means no external preview host is required; it does not remove the release-readiness and rollback checks.

## Delivered in the first Phase 5 slice

- Release identity bound to an approved change-set hash and commit SHA.
- Readiness matrix with automatic checks for change-set approval, verification evidence, blocking
  defects, human acceptance, rollback prerequisites, and supplied external checks.
- Release submission/approval with immutable approval records and segregation of duties.
- Package manifest generation with SHA-256 manifest checksum and immutable release identifier.
- Environment-specific deployment plans containing prechecks, migrations, deployment steps, health
  checks, rollback triggers, and recovery steps.
- Production deployment approval policy: production can require distinct release-management and security
  authority, while the API-only pilot can record the selected automation decisions.
- Deployment records with provider IDs, diagnostics, health checks, and rollback state.
- HTTPS-only deployment and rollback webhook adapter; an unconfigured provider never simulates success.

## Workflow

1. Create a release from an approved change set:
   `POST /api/v1/releases` with `version`, `commit_sha`, `release_notes`, and `rollback`.
2. Evaluate readiness with `POST /api/v1/releases/{id}/readiness`. Supply externally verified checks
   for image, SBOM, migration, configuration, or other project-specific evidence.
3. Approve the submitted release with `POST /api/v1/releases/{id}/approve`.
4. Create and submit a deployment plan using `/api/v1/deployment-plans`.
5. Approve the deployment plan. Production can require a distinct release-manager approval and a
   distinct security-approver approval; the API-only pilot records the configured automation decision.
6. Create a deployment using `POST /api/v1/deployments`. Use `execute: true` only when the provider
   is configured and the deployment is authorized; omitting it records an authorized, unexecuted
   request for operator handoff.
7. Inspect `/api/v1/deployments/{id}` for diagnostics and health evidence. Use the rollback endpoint
   only after a failed or unhealthy deployment and retain the provider response.

For a controlled local non-production target, set `DEPLOYMENT_ADAPTER=local_compose` plus
`LOCAL_COMPOSE_FILE` and `LOCAL_DEPLOYMENT_HEALTH_URL`. Multiple compose files may be supplied as a
comma-separated value, for example `docker-compose.yml,docker-compose.pilot.yml`. This adapter
executes `docker compose up -d`, waits for the configured health URL up to
`LOCAL_DEPLOYMENT_HEALTH_TIMEOUT_SECONDS`, and records output; it is explicitly rejected in
production. A rollback additionally requires `LOCAL_COMPOSE_ROLLBACK_FILE` or a deployment manifest
with `rollback.compose_files`; rollback deploys that previous definition with `docker compose up -d`
and does not use a restart-only shortcut.

Run `scripts/validate_provider_config.py --require-phase5` before the live pilot. It validates the
selected webhook or local Compose adapter, variable names, and URL shape, never secret values or
network health.

## Deployment webhook contract

Configure these variables through the deployment environment or secret store:

```text
DEPLOYMENT_URL=https://deploy.example/api/deploy
DEPLOYMENT_ROLLBACK_URL=https://deploy.example/api/rollback
DEPLOYMENT_TOKEN=<secret-store-reference>
DEPLOYMENT_TIMEOUT_SECONDS=180
```

For local Compose validation, these names may be placed in the ignored `backend/.env` copied from
`backend/.env.example`. Production deployment and rollback tokens must be injected by the target
platform or external secret manager; do not commit them or send them through chat.

The deploy request includes the release version, commit SHA, deployment-plan version/hash, full
validated plan, environment, and rollback metadata. The provider must return:

```json
{
  "status": "healthy",
  "deployment_id": "deploy-123",
  "diagnostics": {"image_digest": "sha256:..."},
  "health_checks": {"ready": true}
}
```

Allowed provider statuses are `queued`, `running`, `healthy`, `failed`, and `rolled_back`. The
control plane rejects non-HTTPS endpoints, invalid status values, and non-object diagnostics or
health-check evidence.

## Recorded local package evidence

- Final image: `sha256:554644c469ce4d12c3c854b281a84e13f0ddd766db0a398c5faacdf0560894da`.
- Image tar SHA-256: `966546741c26e3f81ff2851758384219fb6c79f2adca5be6bb94e03470eb2c0c`.
- `pip-audit` found no known vulnerabilities after upgrading Flask to 3.1.3 and python-dotenv to 1.2.2.
- Earlier local smoke evidence returned `/health` status `ok` after image restoration. The current
  adapter requires an explicit previous Compose definition for a valid rollback; a restart-only
  exercise is not treated as rollback evidence.

- Real approved pilot release and immutable package/image/SBOM/checksum evidence.

The local Compose adapter supports a real rollback only when an explicit previous Compose definition
is supplied through `LOCAL_COMPOSE_ROLLBACK_FILE` or the deployment manifest's
`rollback.compose_files`. Both deploy and rollback run `docker compose up -d` against their respective
definitions and then perform the configured health check. This local evidence does not create the botq
release/deployment records or replace approval of a production deployment.
- Live deployment-provider response and post-deployment smoke/health results.
- Migration and backup evidence, including rollback compatibility.
- Deployment diagnostics across the observation period.
- Policy-driven rollback exercise with a retained successful result.
- Release-manager/security-approver decision records, or API automation decisions when project policy
  selects `api_automation`.

This slice intentionally does not claim that botq deployed the pilot application. The local Docker
smoke test proves container startup and migration compatibility only; a botq release record, approved
deployment plan, health evidence, rollback exercise, and policy-selected API decisions are required to
close Gate 6.
