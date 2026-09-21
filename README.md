# botq - AI Software Delivery Platform

Human-supervised, agentic software delivery platform. Agents (AI or human) propose and
build software in an isolated sandbox, guarded by scope-based RBAC, append-only tamper-evident
audit logging, encrypted secrets, and controlled Git access.

Phase 1 (Foundation) is complete and validated (Gate 1, including a real SSH pilot clone).
Phases 1-6 control-plane workflows are implemented: requirements, architecture/planning,
managed agent execution, UI/UX acceptance, release/deployment, hardening evidence, and the
explicit seven-gate API. Gates can now be configured, evidenced, evaluated, approved by a
human API caller or dedicated automation principal, closed, reopened, and queried through
authorized APIs. Missing or failed evidence remains blocked. See
`docs/IMPLEMENTATION_ROADMAP.md` for the full plan and
`docs/AI_Software_Delivery_Platform_SRS.docx` for the requirements.
The current Phase 4 operator and acceptance runbook is in
`docs/PHASE4_ACCEPTANCE.md`.
The repository-side pilot sequence for Phases 2–4 is in
`docs/PHASE234_PILOT.md`.
Phase 5 release and deployment controls are documented in
`docs/PHASE5_RELEASE_DEPLOYMENT.md`.
The current agreed pilot profile and completion matrix are in
`docs/PILOT_STATUS.md`.

The pilot application repository `git@github.com:cosq-network/botq-dev-pilot-1.git` is now initialized
on `main` at commit `31cbdb1`. Its Flask/PostgreSQL registration-and-login scaffold was smoke-tested
with Docker/PostgreSQL, and its automated tests passed. This initializes the pilot application only;
botq gate closure still requires passing synchronized or submitted evidence and explicit API decisions
under the configured gate policy.

## Phase 1 scope

- Multi-tenant organizations, users, roles and scope-based RBAC
- Projects with SDLC lifecycle state
- Opaque, hashed, revocable bearer tokens (local auth + OIDC-ready providers)
- Append-only audit trail with HMAC-chained event hashes and integrity verification
- Git SSH repository connections: deploy-key provisioning, host-key pinning, rotate/revoke,
  clone/sync (real subprocess backend + fake backend for tests; validated against a live SSH
  remote - see "Phase 1 Gate 1 validation")
- Encrypted secrets manager (Fernet) with masking, redaction and prompt-injection policy
- Docker sandbox: allowlisted images/networks, resource limits, environment-readiness report,
  diagnostic runs, background worker
- Backup/restore baseline: portable, checksummed archives of the full database plus deploy keys
  and (opt-in) workspaces; restores verify integrity and refuse to clobber non-empty targets

## Phase 2 and Phase 3 scope (control plane complete)

- Requirement baselines (REQ-REQ-01): versioned + attributable content (goals, specs,
  constraints, acceptance expectations, attachments, repo references), immutable versions with
  content hashes, diff/compare, submit
- Approval loop (REQ-REQ-03, SRS 4.2): Approve / Request changes / Reject / Waive / Cancel,
  bound to artifact version + content hash; segregation of duties (author cannot self-approve);
  waivers require reason + expiry; approvals are append-only and immutable; a new version
  invalidates prior approval
- Work Items (REQ-REQ-02/06): Epic/Feature/Story/Task/Test Case hierarchy with `KEY-<n>`
  identifiers, acceptance criteria, priority, risk, status, owner; directed dependencies with
  circular-dependency rejection; hierarchy + parent-cycle validation; every item must trace to a
  requirement baseline or be flagged derived
- Requirement analysis (REQ-REQ-02/04): version/hash-bound decomposition runs, auditable
  coverage/consistency findings, blocking-finding approval gates, schema-validated proposals,
  and configurable rules, Heroku Managed Inference, or RunPod Serverless providers
- Architecture and planning (REQ-DES-01..05, REQ-PLN-01..05): approved-baseline-bound
  architecture packages, ADRs, anchored design comments, technical plans with typed environment
  manifests and feasibility sections, traceability links/search, and approval-bound revisions
- Implementation control (REQ-COM-06, REQ-IMP-01..07): approved-plan-bound agent runs,
  pause/cancel/checkpoint state, writable-path enforcement, reviewable change sets, self-review,
  verification evidence, approval gates, and a leased Heroku/RunPod implementation worker

## Layout

```
  backend/
  app/
    auth/      roles, scopes, tokens, local + OIDC providers, auth routes
    orgs/      bootstrap organization service + routes
    projects/  project CRUD routes
    requirements/ baseline intake, AI decomposition, findings, provider adapters (REQ-REQ-01/04)
    architecture/ versioned architecture packages, ADRs, comments, review gates (REQ-DES-01..05)
    artifacts/   shared artifact versioning and content hashing
    planning/    technical plans, agent runs, checkpoints, change sets, verification (REQ-PLN/IMP)
    traceability/ cross-artifact links and search (REQ-COM-05/07)
    design/     Penpot references, mockup review, previews, HAT, defects (Phase 4 start)
    approvals/ immutable approval records bound to version+hash, segregation of duties (REQ-REQ-03)
    work_items/ Epic/Feature/Story/Task/Test Case hierarchy, dependencies, cycles (REQ-REQ-02/06)
    git/       backend abstraction, ssh keys, adapter, routes
    secrets/   encryption, masking, injection policy, routes
    sandbox/   readiness report, docker runner, routes, background worker
    audit/     HMAC chained audit service + routes
    backup/    backup/restore service + `flask backup` CLI
    api/       blueprint aggregator (default-deny auth), responses, health
    templates/ index page
  migrations/  Alembic (cb3a5dae0416 initial ... f2a7c9e4d1b6 project gate control)
  tests/       pytest suite (156 tests)
  Dockerfile  gunicorn image (openssh-client, git, node/npm, C/C++ toolchain, docker SDK)
  pyproject.toml  ruff + pytest configuration
docker-compose.yml   db + api + worker + nginx proxy
nginx/default.conf   reverse proxy on :8080
dev/git-fixture/     throwaway real SSH git remote (compose "git-validation" profile)
scripts/             validate_git.ps1 (Phase 1 pilot-clone), phase2_demo.py (Phase 2 flow)
.github/workflows/ci.yml
```

## Quickstart

Prerequisites: Docker with Compose v2.

```sh
cp backend/.env.example backend/.env   # set SECRET_KEY and AUDIT_SECRET
export POSTGRES_PASSWORD='use-a-long-random-password'
docker compose up -d --build

# apply schema and create the first organization + administrator
docker compose exec api flask db upgrade
docker compose exec api flask bootstrap --org-name "Acme" --slug "acme" \
    --email "admin@acme.local" --password "ChangeMe123!"

curl -s localhost:8080/health/ready
curl -s localhost:8080/api/v1/auth/providers
```

Log in to get a token:

```sh
TOKEN=$(curl -s -X POST localhost:8080/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@acme.local","password":"ChangeMe123!","organization":"acme"}' \
  | python -c "import sys,json;print(json.load(sys.stdin)['data']['token'])")
curl -s localhost:8080/api/v1/organizations/me -H "Authorization: Bearer $TOKEN"
```

During bootstrap only, organization creation/list also accepts `X-Bootstrap-Token`
(must match `SECRET_KEY`). Disable it in production by removing the header path.

## Phase 1 Gate 1 validation (real clone)

`scripts/validate_git.ps1` proves the pilot-repository clone against a **real** SSH Git remote
(the `git-fixture` service, gated behind the `git-validation` compose profile so it never runs
in normal deployments), exercising the actual `GitCommandBackend` end to end:

```sh
docker compose --profile git-validation up -d --build
docker compose exec api flask db upgrade
docker compose exec api flask bootstrap --org-name "Acme" --slug "acme" \
    --email "admin@acme.local" --password "S3curePass!"
pwsh -File scripts/validate_git.ps1 -ProjectKey pilotlive
```

It drives connect -> deploy-key provisioning -> host-key scan -> `ls-remote` test -> clone ->
server-side commit -> fetch/fast-forward sync (head advances) -> key rotation -> revoke, and
asserts the audit lifecycle and chain integrity. Tear it down with
`docker compose --profile git-validation stop git-fixture`.

## Requirement baselines

Phase 2 requirement intake. A baseline is versioned and attributable: each revision stores an
immutable content snapshot with a SHA-256 hash, and versions can be compared before submission.

```sh
curl -s -X POST localhost:8080/api/v1/requirements/baselines \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"project_id":"<id>","title":"Pilot Intake","content":{"goals":["Deliver safely"]}}'

curl -s -X POST localhost:8080/api/v1/requirements/baselines/<id>/versions \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"content":{"goals":["Deliver safely","Reduce toil"]}}'

curl -s "localhost:8080/api/v1/requirements/baselines/<id>/versions/1/diff?to=2" \
  -H "Authorization: Bearer $TOKEN"
curl -s -X POST localhost:8080/api/v1/requirements/baselines/<id>/submit \
  -H "Authorization: Bearer $TOKEN"
```

Content supports `goals`, `functional_specifications`, `constraints`, `acceptance_expectations`,
`attachments` and `repository_references`; at least one goal is required. Versions are
append-only (update/delete raise `PermissionError`), matching the audit-trail policy.

## Approvals and work items

A submitted baseline is reviewed with the approval loop, which binds each decision to the exact
version + content hash and enforces segregation of duties (the author cannot approve their own
work):

```sh
curl -s -X POST localhost:8080/api/v1/requirements/baselines/<id>/approve \
  -H "Authorization: Bearer $REVIEWER_TOKEN"        # requires 'approval' scope, not the author
curl -s -X POST localhost:8080/api/v1/requirements/baselines/<id>/waive \
  -H "Authorization: Bearer $REVIEWER_TOKEN" -H 'Content-Type: application/json' \
  -d '{"reason":"pilot exception","expires_at":"2030-01-01T00:00:00"}'
```

Work items form an Epic > Feature > Story > Task/Test Case hierarchy under a project, each
`KEY-<n>` identified, traced to a baseline (or marked derived), with directed dependencies that
reject cycles:

```sh
curl -s -X POST localhost:8080/api/v1/work-items \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"project_id":"<id>","kind":"epic","title":"Platform","source_baseline_id":"<baseline>"}'
curl -s -X POST localhost:8080/api/v1/work-items/<id>/dependencies \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"depends_on_id":"<predecessor>"}'
```

`scripts/phase2_demo.py` drives the whole intake -> approval -> work-item flow against a running
stack and asserts audit-chain integrity:

```sh
docker compose exec api flask db upgrade
python scripts/phase2_demo.py
```

## Requirement analysis providers

Week 9 analysis is provider-neutral. `rules` is the deterministic local/CI provider. For managed
inference, set `REQUIREMENT_ANALYSIS_PROVIDER=heroku` or `runpod`. To configure an ordered fallback,
use a comma-separated value such as `heroku,runpod`; the next provider is attempted only when the
previous provider fails. Credentials remain environment variables and are never returned by the API.

Heroku uses its OpenAI-compatible Managed Inference chat endpoint:

```sh
REQUIREMENT_ANALYSIS_PROVIDER=heroku
HEROKU_INFERENCE_BASE_URL=https://<region>.inference.heroku.com
HEROKU_INFERENCE_KEY=<INFERENCE_KEY>
HEROKU_INFERENCE_MODEL=<provisioned-chat-model>
HEROKU_INFERENCE_MAX_TOKENS=4096
```

RunPod uses a Serverless `runsync` endpoint whose worker accepts `input.system_prompt` and
`input.prompt` and returns the JSON analysis document:

```sh
REQUIREMENT_ANALYSIS_PROVIDER=runpod
RUNPOD_API_KEY=<api-key>
RUNPOD_ENDPOINT_ID=<serverless-endpoint-id>
# Optional when using a compatible gateway or custom URL.
RUNPOD_INFERENCE_URL=https://api.runpod.ai/v2/<endpoint-id>/runsync
```

The remote output must contain `findings` and `proposed_work_items` in the documented schema. The
API rejects invalid output before storing it, and unresolved blocking findings prevent requirement
baseline approval. The provider prompt and policy versions are recorded on every analysis run.

The Phase 3 worker uses the same provider portability rule, with
`AGENT_IMPLEMENTATION_PROVIDER=heroku`, `runpod`, or `heroku,runpod`. Its response must contain a
non-empty `changes` array, each with a safe relative path, `add`/`modify`/`delete` action, and diff,
plus `self_review.result`. Invalid or out-of-scope output fails the run and is never persisted as a
successful change set.

## Architecture, planning, and implementation gates

Architecture packages can only be created from an approved requirement baseline. Technical plans
can only be created from an approved architecture package, and agent runs can only be created from
an approved plan. Every revision stores a new content hash and invalidates downstream approval
state. Agent runs record their plan hash, tools, writable paths, environment, model configuration,
budget, events, checkpoints, worker lease, and attempt count. Run permissions are intersected with
the approved plan permissions. Change-set files outside the approved writable paths are rejected;
verification evidence must identify the exact change-set hash, and all verification records must
pass or carry an unexpired, authorized waiver before a change set can be submitted for approval.

The Compose worker runs `python -m app.sandbox_worker`. It now polls queued agent runs, claims them
with a database lease, resumes from the latest checkpoint, and asks the configured implementation
provider for a strict JSON change set. Set `AGENT_IMPLEMENTATION_PROVIDER=heroku`, `runpod`, or
`heroku,runpod`; leave it `disabled` until credentials and a pilot repository are approved. The
worker stores a draft change set only. It does not apply model output, approve changes, or claim
that tests passed. A run must provide `environment.branch` and `environment.base_commit`; optional
`environment.repository_snapshot` supplies non-secret repository context to the model.

## Phase 4 design and acceptance

Phase 4 is API-first and keeps approval control explicit. Mockups are immutable, versioned artifacts
that require an approved architecture, can reference a Penpot file/page/node, and use the same
version + content-hash approval loop as architecture and plans. Penpot writes and comments are
never simulated: when the configured read adapter cannot perform a capability, the API returns a
documented human handoff.

Preview records are pinned to the approved mockup hash and commit SHA, require an authenticated
non-production access policy, and expire automatically at the policy boundary. Acceptance
sessions record per-criterion Pass/Fail/Blocked/N-A results and evidence. Defects include
reproduction data and cannot close without passed regression evidence when a regression test is
required.

The initial endpoints are under /api/v1/design: /mockups, /previews, /acceptance/sessions, and
/defects. Configure a read-only Penpot adapter with PENPOT_API_BASE_URL, PENPOT_API_TOKEN, and
optionally PENPOT_FILE_PATH; credentials are environment configuration and are not stored in
design records. The `/workbench` route provides a same-origin, keyboard-accessible operator surface
for mockup/preview review, HAT result recording, and defect triage. It remains a control surface:
preview hosting and Penpot writes are still external operations unless configured through approved
adapters. Sign-off can be recorded by assigned human users or by an authorized automation principal
when project policy selects the API-only pilot mode.

## Phase 5 release and deployment

Phase 5 now provides release identity and readiness checks, immutable package manifests, environment-
specific deployment plans, production dual-control validation, deployment diagnostics, and rollback
records under `/api/v1/releases`, `/api/v1/deployment-plans`, and `/api/v1/deployments`. Actual host
operations use the configured HTTPS deployment webhook and fail closed when it is not configured.
See `docs/PHASE5_RELEASE_DEPLOYMENT.md`.

## Phase 6 hardening

Phase 6 now includes correlation IDs, security headers, request metrics, a configurable rate-limit
baseline, safe diagnostic bundles, retention planning/execution, recovery evidence helpers, and
observability checks. See `docs/PHASE6_HARDENING.md`; production-scale evidence still has to be
captured for a production readiness claim.

## Explicit gate control API

Gate policy is available at `/api/v1/organizations/me/gate-policy` and
`/api/v1/projects/{project_id}/gate-policy`. The pilot can select `api_automation`, create an
automation principal through the organization user API, submit or synchronize evidence, record
automation decisions with evidence hashes, and close/reopen gates through `/api/v1/projects/{id}/gates`.
The API never converts missing, expired, failed, or unavailable evidence into success.

## Dedicated API E2E suite

The repository includes a Dockerized HTTP E2E suite covering the API workflow
from authentication and requirements through approvals, agent runs, previews,
acceptance, releases, deployment authorization, secrets, audit, sandbox, and
repository controls. Run it with Docker Desktop using
[`scripts/run_e2e.ps1`](scripts/run_e2e.ps1); details and opt-in integration
boundaries are documented in [`docs/E2E_TESTING.md`](docs/E2E_TESTING.md).

## Running a pilot

Use [`docs/PILOT_EXECUTION_GUIDE.md`](docs/PILOT_EXECUTION_GUIDE.md) as the end-to-end pilot runbook.
It covers `.env` setup, provider and repository preflight, Gates 1–7, evidence capture, approvals,
rollback, and cleanup. Keep `AGENT_IMPLEMENTATION_PROVIDER=disabled` until the provider preflight and
Gates 2/3 are complete.

## Backup and restore

A backup is a portable `.tar.gz` containing a logical database dump (every table, with
`audit_events` kept in chain order), a checksummed `manifest.json`, and optionally the
per-project deploy keys and sandbox workspaces.

```sh
docker compose exec api flask backup create -o /backups/botq.tar.gz
docker compose exec api flask backup verify /backups/botq.tar.gz
docker compose exec api flask backup restore /backups/botq.tar.gz --dry-run
docker compose exec api flask backup restore /backups/botq.tar.gz --replace
```

Restores verify the payload SHA-256 before writing and refuse to overwrite a non-empty
database unless `--replace` is passed. `--include-workspaces` opts workspaces into the
archive (off by default). Keep `SECRET_KEY`/`SECRET_ENCRYPTION_KEY` and `AUDIT_SECRET`
safe separately: encrypted secrets and audit hashes cannot be recovered without them.

## Key configuration

| Variable | Purpose | Default |
| --- | --- | --- |
| `APP_NAME` / `ENVIRONMENT` | Application label and runtime environment | `botq` / `development` |
| `DATABASE_URL` | SQLAlchemy URL | `postgresql+psycopg2://botq:botq@localhost:5432/botq` |
| `SECRET_KEY` | Bootstrap token + derived encryption/base | `change-me-in-production` |
| `AUDIT_SECRET` | HMAC key for the audit chain | `change-me-audit-chain-secret` |
| `SECRET_ENCRYPTION_KEY` | Explicit Fernet key (base64). If empty, derived from `SECRET_KEY` | `""` |
| `OIDC_ENABLED` / `OIDC_ISSUER` / `OIDC_CLIENT_ID` | Optional production OIDC settings | `false` / empty / empty |
| `OIDC_CLIENT_SECRET` | OIDC client secret; runtime secret only | empty |
| `REQUIREMENT_ANALYSIS_PROVIDER` | Requirement provider order: `rules`, `heroku`, `runpod` | `rules` |
| `REQUIREMENT_ANALYSIS_TIMEOUT_SECONDS` | Requirement provider timeout | `120` |
| `HEROKU_INFERENCE_*` / `RUNPOD_*` | Managed inference endpoints, models, and runtime credentials | empty |
| `GIT_KEY_DIR` / `GIT_KNOWN_HOSTS` | Deploy key + known_hosts storage | `secrets/git` |
| `SANDBOX_IMAGES_ALLOWLIST` | Comma-separated allowlisted images | `python:3.13-slim,node:22-bookworm,botq/toolchain:latest` |
| `SANDBOX_NETWORK_ALLOWLIST` | Allowed container networks | `none,host` |
| `SANDBOX_ALLOW_PRIVILEGED` / `SANDBOX_ALLOW_HOST_MOUNTS` | Explicit high-risk sandbox controls | `false` / `false` |
| `AGENT_IMPLEMENTATION_PROVIDER` | Phase 3 implementation provider order | `disabled` |
| `AGENT_IMPLEMENTATION_MODEL` | Optional model override for Heroku-compatible inference | empty |
| `AGENT_IMPLEMENTATION_TIMEOUT_SECONDS` | Managed implementation request timeout | `180` |
| `AGENT_WORKER_LEASE_SECONDS` | Durable agent-run lease duration | `900` |
| `AGENT_WORKER_POLL_SECONDS` | Worker polling interval | `30` |
| PENPOT_API_BASE_URL / PENPOT_API_TOKEN | Optional read-only Penpot adapter | empty |
| PENPOT_FILE_PATH | Configured Penpot file metadata path | /api/files/{file_id} |
| PENPOT_API_TIMEOUT_SECONDS | Penpot adapter request timeout | 15 |
| `PREVIEW_DEPLOYMENT_URL` / `PREVIEW_DEPLOYMENT_TOKEN` | Optional HTTPS preview-host provisioning webhook | empty |
| `PREVIEW_DEPLOYMENT_TIMEOUT_SECONDS` | Preview-host request timeout | `120` |
| `DEPLOYMENT_URL` / `DEPLOYMENT_TOKEN` | Phase 5 deployment webhook | empty |
| `DEPLOYMENT_ROLLBACK_URL` | Optional Phase 5 rollback webhook | `DEPLOYMENT_URL` |
| `DEPLOYMENT_TIMEOUT_SECONDS` | Deployment provider timeout | `180` |
| `RATE_LIMIT_ENABLED` / `RATE_LIMIT_PER_MINUTE` | Phase 6 request protection baseline | `false` / `120` |
| `RETENTION_AUDIT_DAYS` | Audit retention planning horizon | `365` |
| `RETENTION_AGENT_EVENT_DAYS` | Agent event retention planning horizon | `90` |
| `RETENTION_CHECKPOINT_DAYS` | Checkpoint retention planning horizon | `30` |
| `GIT_ADAPTER_FACTORY` | Optional callable returning a `GitAdapter` (used by tests) | - |

For local development, copy `backend/.env.example` to `backend/.env`; the latter is ignored by
Git. Set provider, repository, Penpot, preview, and deployment values there only when running a
local or Compose pilot. For production, inject the same variable names through the deployment
platform or an external secret manager. Put actual API keys, client secrets, deployment tokens,
Fernet keys, and database credentials only in runtime secret injection—not in Git, project records,
prompts, logs, or chat. Run `scripts/validate_provider_config.py --json` after configuration;
it validates names and HTTPS URL shape without printing secret values or probing the network.

## Tests and lint

```sh
.\.venv\Scripts\python.exe -m pytest          # full suite
.\.venv\Scripts\python.exe -m ruff check .    # lint
.\.venv\Scripts\python.exe -m ruff format --check .
```

## Security model

- API endpoints default to denied; only an explicit allowlist (`/ping`, login, providers,
  OIDC flow, org bootstrap) is public.
- Every object carries its tenant (`organization_id`); queries are scoped in the request context.
- Audit events are append-only at the ORM level (update/delete raise `PermissionError`) and
  each event's hash chains to the previous event per tenant.
- Secrets are encrypted at rest with Fernet and never returned by the API (masked).
- Sandbox containers never run privileged and are restricted to allowlisted images and networks.
- The Docker socket is mounted only into control-plane services (`api`, `worker`), never exposed
  to agent runtime.
