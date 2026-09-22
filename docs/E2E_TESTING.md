# Dockerized API E2E testing

The repository now includes a dedicated HTTP-level E2E suite in `e2e/`. It
drives the deployed Flask API through the nginx proxy and PostgreSQL container;
it does not use Flask's test client or a SQLite substitute.

## Run locally

From the repository root, with Docker Desktop running:

```powershell
./scripts/run_e2e.ps1
```

The runner builds the API and worker images, creates an isolated Compose
project and volumes, applies migrations, seeds test users, waits for
`/health/ready`, runs `pytest e2e`, and removes the Compose project and its
volumes in a `finally` block.

The defaults are:

- API: `http://127.0.0.1:8885` (override with `BOTQ_E2E_PORT` or `BOTQ_E2E_BASE_URL`)
- organization: `acme`
- administrator: `admin@acme.local`
- reviewer: `reviewer@acme.local`
- password: `E2ePass!2026`

These are test-only values. Override them with `BOTQ_E2E_*` environment
variables when needed. The test Compose override forces rules-based requirement
analysis and disables the implementation worker provider, so Heroku or RunPod
credentials are never called by the suite.

## Coverage

The suite exercises the real API boundary for authentication, health and
organization discovery, projects, requirements and analysis, work-item
hierarchy/dependencies, architecture and approvals, technical plans, agent-run
controls, change sets and verification, traceability, design/mockups, previews,
human acceptance, defects, releases, deployment plans/deployment authorization,
secrets, audit/diagnostics, sandbox controls, repository controls, gate policy,
gate evidence/evaluation/decision APIs, API automation approval, and gate summary.

The repository API is tested safely without an external Git host: read and
missing-connection controls are exercised, and connection provisioning is
asserted to fail closed when no validated remote is configured. Production
deployments should validate their approved Git host through the configured
repository connection and host-key policy.

External provider success paths are intentionally not part of the default E2E
run. They require real credentials and a non-production endpoint. Provider
adapter integration tests in `backend/tests/test_provider_integrations.py` cover request,
authentication, response, redaction, rollback, and schema-constrained inference behavior with
deterministic HTTP mocks. A safe connectivity probe is available through the opt-in
`BOTQ_EXTERNAL_PROVIDER_URL` CI secret; it does not perform provider mutations.

## Frontend verification

The Docker runner also installs the frontend from the lockfile and executes the production-like
SPA behind the same Nginx origin. The Playwright suite covers unauthenticated redirects, login
surface labels, authenticated domain routes, nested detail routes, and axe checks on the major
screens. The current verified run completed 27 browser tests with no failures.

Frontend dependency generation and checks are also available locally:

```powershell
Push-Location frontend
npm ci
npm run generate:api
npm run generate:hooks
npm run typecheck
npm run lint
npm test
npm run audit
npm run build
Pop-Location
```

## CI

The CI workflow runs the same suite after lint/unit validation using the
Compose E2E runner. A failed readiness check, migration, HTTP contract, or
workflow gate fails the job and preserves the response body in pytest output.

The backend unit suite currently includes focused API-only gate coverage for policy inheritance,
automation principals, evidence idempotency, auto-approval, closure blocking, reopen behavior, and
gate summary. Keep those tests green alongside the Dockerized E2E suite when changing gate policy or
approval behavior.
