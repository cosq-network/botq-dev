# botq Pilot Execution Guide

**Status:** Operational runbook for the first controlled pilot

This guide explains how to run one end-to-end botq pilot and collect evidence for Gates 1–7. It is a
runbook for validating the implemented control plane with a real repository, selected managed-inference
provider, preview environment, and API-recorded gate decisions. It is not a production-readiness approval by itself.

## Agreed pilot profile

The first pilot has the following non-secret decisions recorded:

| Item | Decision |
| --- | --- |
| Inference provider | Heroku managed inference |
| Inference endpoint | `https://us.inference.heroku.com` |
| Inference model | `nova-2-lite` |
| Pilot repository | `git@github.com:cosq-network/botq-dev-pilot-1.git` |
| Branch | `main` |
| GitHub host key | `SHA256:qQSTyn6li7lXUuoTW1WA3hWCoh4wn4WGKvu6JYYs3cM` |
| Preview | Local-only |
| Deployment | Local Docker Compose |
| SLA / RPO / RTO | 99.5% / 24 hours / 8 hours |
| Gate approval mode | API automation pilot |
| Automation principal | Dedicated organization user with least-privilege roles |
| Pilot feature | Registration and login |
| Application stack | Python Flask + PostgreSQL, server-rendered templates |
| Authentication | Email/password, Argon2id, secure sessions, CSRF, logout |
| Session and protection | 8-hour sessions; 5 failed attempts per 15 minutes per account/IP |
| Out of scope | Email verification, password reset, MFA, external preview |

The pilot application was initialized from the empty repository and pushed to `main` in commit
`31cbdb1`. The Heroku authentication key is intentionally not recorded here; it must remain in the
ignored botq `backend/.env` file.
The adapter uses `HEROKU_INFERENCE_MAX_TOKENS=4096` by default for structured responses and rejects
malformed or schema-incomplete output.

## 1. Pilot shape

Use a small, representative project with one organization, one project, one authorized Git repository,
one pilot feature, and a limited set of reviewers. Keep the pilot environment separate from production and
use synthetic or approved non-sensitive data.

The recommended first topology is:

- botq control plane running with Docker Compose on a controlled Docker host or VPS;
- PostgreSQL as the system database;
- Heroku inference as the primary provider, RunPod as fallback, or either provider alone;
- a protected HTTPS preview environment with an expiry date;
- explicit API approval decisions before any generated change set, release, or deployment is accepted.

The provider choice is project-level runtime configuration. It does not require a separate botq codebase for
each project. Keep `AGENT_IMPLEMENTATION_PROVIDER=disabled` until the provider preflight and Gates 2/3 are
complete.

## 2. Information and access required

Decide and record these items before the live pilot:

| Item | Example | Supply method |
| --- | --- | --- |
| Pilot project | `pilot-storefront` | Reply or record in the pilot evidence package |
| Repository | `git@github.com:example/storefront.git` | Project record or pilot runbook; never put private keys in it |
| Branch | `main` | Project record |
| Inference | `heroku`, `runpod`, or `heroku,runpod` | `backend/.env` or deployment secret configuration |
| Preview | Protected temporary HTTPS host | `PREVIEW_DEPLOYMENT_*` settings and evidence |
| Deployment target | Controlled Docker host, Heroku, customer environment, etc. | `DEPLOYMENT_*` settings and release plan |
| SLA/RPO/RTO | For example 99.5% / 24 hours / 8 hours | Pilot decision record |
| Decision principal | Dedicated automation user, or named human reviewers when policy changes | Organization user/role APIs and approval records |

Credentials, tokens, private keys, and endpoint secrets must be supplied through `backend/.env` for local
work or the target platform's secret manager for deployment. Do not paste them into chat, project records,
prompts, logs, screenshots, or Git.

## 3. Prepare the local environment

From the repository root in PowerShell:

```powershell
Copy-Item backend/.env.example backend/.env
```

Edit `backend/.env`. At minimum, replace the development secrets and choose the providers. A deterministic
local pilot can begin with `REQUIREMENT_ANALYSIS_PROVIDER=rules`; live analysis and implementation require
the selected managed-inference settings.

```dotenv
ENVIRONMENT=development
SECRET_KEY=<long-random-value>
AUDIT_SECRET=<different-long-random-value>
REQUIREMENT_ANALYSIS_PROVIDER=rules
AGENT_IMPLEMENTATION_PROVIDER=disabled
# Set Heroku/RunPod, Penpot, preview, and deployment values only when those stages are approved.
```

For a Compose database password, set the process environment variable without committing it:

```powershell
$env:POSTGRES_PASSWORD = '<long-random-value>'
```

Start and initialize the stack:

```powershell
docker compose up -d --build
docker compose exec api flask db upgrade
docker compose exec api flask bootstrap --org-name "Pilot Org" --slug pilot --email pilot-admin@example.invalid --password "<temporary-strong-password>"
Invoke-RestMethod http://localhost:8884/health/ready
Invoke-RestMethod http://localhost:8884/api/v1/auth/providers
```

The pilot proxy override is intentionally an override, not a standalone Compose project. Use it with
the base file and the same dotenv file when the pilot runner expects port `8886`:

```powershell
docker compose --env-file backend/.env -f docker-compose.yml -f docker-compose.pilot.yml up -d --build
```

If another local pilot already uses `8886`, select another loopback port for this isolated run, for
example `$env:BOTQ_PILOT_PORT = '18083'`, and pass that port to the pilot scripts with
`--base-url http://127.0.0.1:18083`.

Use an address and password intended only for the pilot. Change or remove the bootstrap account after the
pilot according to the environment's access policy.

## 4. Run preflight and preserve evidence

Run these checks before connecting a live provider or repository. The commands assume the project virtual
environment is at `backend/.venv`; use the equivalent interpreter if your environment differs.

```powershell
$env:PYTHONPATH = (Resolve-Path backend).Path
& .\backend\.venv\Scripts\python.exe scripts/validate_provider_config.py --json
& .\backend\.venv\Scripts\python.exe scripts/validate_security_baseline.py --json
& .\backend\.venv\Scripts\python.exe scripts/validate_accessibility.py --json
& .\backend\.venv\Scripts\python.exe -m ruff check backend/app backend/tests scripts
& .\backend\.venv\Scripts\python.exe -m compileall -q backend/app backend/tests scripts
git diff --check
```

### Current live checkpoint (2026-09-19)

The botq API, worker, and PostgreSQL services were started in Docker Compose and the internal readiness
check returned HTTP 200. A BotQ Pilot requirements baseline was analyzed through Heroku `nova-2-lite`:
the provider returned 0 findings and 12 proposals, the proposals were applied, and the baseline was
submitted for review. The baseline identifier is `3de28ab9-d030-45fb-9a56-5d12325b5d99` and its current
content hash is `5e395548ccb362a5c1ac428ddb6299e96d18c004445b3f6276c9f2da7d3c3152`. The GitHub deploy key was subsequently authorized; botq's repository connection
test passed and `main` synchronized successfully at commit `31cbdb1e31a120c0f90ce2e8c638957e2ba68aeb`.
No human approval is implied by this checkpoint.

### Verified execution update (2026-09-20)

The local botq pilot created and approved a baseline, architecture package, and technical plan. The
Heroku `nova-2-lite` worker claimed run `3088fe0b-e82c-4249-8d88-0bafa57a3e5b` and produced reviewable
change set `02b9209b-45e4-448c-98db-5f545a851326` with eight files. The generated set was inspected
and rejected because it invented an incompatible Flask structure and dependencies; it was not applied
or approved. The local BotQ preview then passed six automated HAT criteria, the remediated image had a
clean dependency audit, local rollback/restore health passed, and the Phase 6 latency/backup/PostgreSQL
restore exercises passed. Gate 4 verification, botq-controlled Gate 6 execution, Gate 5 automated
acceptance evidence, and Gate 7 production-readiness evidence remain open until submitted and closed
through the gate API.

### Gate 4 rerun update (2026-09-20)

A constrained rerun supplied the exact current `tests/test_auth.py` source to Heroku and limited the
output to one test-only change. It completed as run `d883eb1d-a73f-4399-86dd-18762a25d452`, with
one-file draft `ec754484-9aaa-4918-8331-a160f3e3535e` (`01a8aa393cedfeaad914bb69bcf0d68772413eac64126e98e325377cc72dcad5`)
and 2,040 reported tokens. Review correctly rejected it because the emitted unified-diff context did
not apply to the exact supplied file. The worker now performs that applicability check before it
persists a draft, so a future run must produce an applicable diff before test/scan evidence can be
recorded. Provider metadata is never treated as verification evidence.

Store the redacted JSON results, timestamps, commit SHA, configuration summary, and operator name in an
approved evidence location outside the Git repository. Never store the values of secrets. Run the focused
tests described in `API_GATE_CONTROL_GUIDE.md`, `E2E_TESTING.md`, and
`PHASE6_OPERATIONS.md`. If a local Windows ACL or tooling problem prevents a test, record it as an
environment limitation and run the authoritative suite in the Linux CI/Docker environment.

## 5. Configure the API-only gate policy

For this pilot, create a dedicated automation principal and select `api_automation` on the project:

```text
PATCH /api/v1/projects/{project_id}/gate-policy
{
  "approval_mode": "api_automation",
  "require_gate_decisions": true,
  "require_project_responsibility_assignment": false,
  "allow_waivers": true,
  "require_previous_gate_closed": true,
  "auto_sync_evidence": true
}
```

Each gate then follows the same API sequence:

```text
POST /api/v1/projects/{project_id}/gates/{gate_number}/sync
POST /api/v1/projects/{project_id}/gates/{gate_number}/evidence
POST /api/v1/projects/{project_id}/gates/{gate_number}/evaluate
POST /api/v1/projects/{project_id}/gates/{gate_number}/auto-approve
POST /api/v1/projects/{project_id}/gates/{gate_number}/close
```

`close` must fail if evidence is missing, expired, failed, or blocked, or if a previous gate remains
open under the sequential policy.

For a repeatable run, prepare an evidence manifest and execute:

```powershell
$env:BOTQ_PROJECT_ID = "<project-id>"
$env:BOTQ_ADMIN_EMAIL = "<admin-email>"
$env:BOTQ_ADMIN_PASSWORD = "<admin-password>"
$env:BOTQ_AUTOMATION_EMAIL = "<automation-email>"
$env:BOTQ_AUTOMATION_PASSWORD = "<automation-password>"
python scripts/run_api_gate_lifecycle.py --evidence-manifest .pilot-evidence/gates.json
```

The runner submits only manifest evidence that is missing after `sync`; it fails closed when a
mandatory check has no evidence.

## 6. Execute the gates

### Gate 1 — Repository and diagnostic foundation

Use an authorized pilot repository and verify its SSH host key before connecting it. The repository-side
fixture can be exercised with:

```powershell
pwsh -File scripts/validate_git.ps1 -ProjectKey pilotlive
```

For the real pilot, create the project, connect its repository, test the connection, and perform a read-only
sync. Confirm that the configured default branch and host-key fingerprint are correct. Rotate or revoke the
pilot deploy key when the pilot ends. The detailed API contract is in `backend/app/git/routes.py` and the
fixture flow is in `scripts/validate_git.ps1`.

### Gates 2 and 3 — Requirements and architecture

1. Create a requirement baseline for the pilot feature and add an immutable version.
2. Run deterministic analysis first. If live analysis is approved, configure Heroku/RunPod and capture the
   provider, model, prompt, policy, input hash, and output hash.
3. Resolve or formally waive blocking findings. Create traceable work items with acceptance criteria.
4. Generate the architecture package and ADRs from the approved baseline. Add repository, requirement,
   architecture, and work-item trace links.
5. Record the policy-selected approval decision. Approval must reference the exact version and content hash.

Do not proceed to implementation because a draft looks plausible. A changed baseline or architecture
invalidates downstream approvals and requires a new version.

### Gate 4 — Managed inference and implementation

After Gates 2/3 are approved, configure one of:

```dotenv
AGENT_IMPLEMENTATION_PROVIDER=heroku
# or runpod
# or heroku,runpod
```

Run the worker in the Linux Docker environment and watch its logs:

```powershell
docker compose up -d worker
docker compose logs -f worker
```

Use a branch or commit explicitly allowed by the approved plan. Inspect the generated draft change set,
run the required tests and security scans, and attach verification evidence to the exact change-set hash.
The worker must not bypass review or apply model output directly to an approved branch. The automation
principal may approve only a valid persisted change set with passing evidence.

### Gate 5 — UI/UX, preview, and acceptance

Connect the approved Penpot file or project, review the mockup, and link the pilot story to the design nodes.
Provision a protected, non-production HTTPS preview with an expiry. Run the acceptance checklist with the
Product Owner, Designer, and QA; record browser/device, result, defect IDs, screenshots or links, and the
preview commit SHA. Resolve or explicitly disposition regression-gated defects. For the API-only pilot,
the automated accessibility baseline can satisfy the Gate 5 accessibility check only when the policy and
evidence explicitly state automated acceptance; manual review remains optional evidence.

See `FRONTEND_ROUTE_COVERAGE.md` and `E2E_TESTING.md` for the current Penpot, preview, HAT,
accessibility, route, and browser-verification coverage.

### Gate 6 — Release and controlled deployment

Build the immutable image and collect its digest, SBOM, vulnerability result, and checksum. Create a release
bound to the approved change-set and verification evidence. Record prechecks, migrations, backups, health
checks, rollback triggers, and the prior deployable version.

Use the configured release policy for production or production-like deployment. Deploy only through the
approved deployment adapter with `execute=true` after the plan is approved. Check readiness and application
health, retain the deployment diagnostics, and perform the documented rollback check when the pilot target
permits it.

The endpoint and payload contract are documented in `API_GATE_CONTROL_GUIDE.md` and the generated
OpenAPI contract at `/openapi.json`.

### Gate 7 — Hardening and exit review

Run the live security baseline and dependency scan, tenant-isolation review, latency benchmark, backup/restore
exercise, checkpoint restart test, metrics and alert verification, and retention/localization checks. The
benchmark helper is:

```powershell
& .\backend\.venv\Scripts\python.exe scripts/benchmark_api.py --url http://localhost:8884 --json
```

Use `scripts/validate_recovery.py` with a disposable recovery target and record actual RPO/RTO results.
Record Security and Operations readiness evidence/decisions through the API and decide whether the pilot
meets the chosen SLA, RPO, and RTO.

## 7. Pilot evidence checklist

The pilot is ready for exit review when the evidence package contains, at least:

- pilot scope, project, repository, branch, commit SHAs, and named owners;
- provider preflight and redacted runtime configuration summary;
- Git host-key verification, connection test, sync result, and key rotation/revocation result;
- approved requirement baseline, analysis result, architecture/ADR package, trace links, and approval hashes;
- agent-run events, draft change-set hash, tests, scans, verification evidence, and policy-selected Developer/QA decisions;
- Penpot reference if in scope, preview URL and expiry, HAT results, defects, accessibility baseline,
  automated-acceptance policy statement, and any optional manual sign-offs;
- image digest, SBOM, release record, deployment health, rollback evidence, and diagnostics;
- security, performance, recovery, checkpoint, metrics, alerting, retention, and localization results;
- explicit list of accepted limitations, waivers with expiry, and items deferred to production readiness.

Stop the pilot and escalate when a secret is exposed, a repository path is outside the approved scope, a
blocking finding cannot be resolved or waived, readiness fails, a deployment is unhealthy, verification is
not bound to the reviewed hash, or a required reviewer is unavailable.

## 8. Closeout and rollback

If the pilot fails acceptance, stop the worker, preserve diagnostics, disable the preview, and roll back to the
last known-good release according to the approved plan. Revoke or expire temporary preview credentials and
Git deploy keys. Rotate any credential that may have been exposed. Preserve audit events and evidence before
cleanup.

For a local-only teardown, after backups and evidence are confirmed:

```powershell
docker compose down
```

Do not remove volumes or backups as part of routine teardown; delete them only under an explicitly approved
retention/cleanup decision.

## 9. What the pilot does and does not prove

The pilot proves that the selected control-plane workflow can be exercised end to end with the chosen
provider, repository, preview path, deployment path, and API-recorded approval decisions. It does not automatically prove a
production SLA, multi-tenant scale, full disaster recovery, long-term retention compliance, or manual
accessibility conformance. Those claims require the corresponding live evidence and approvals recorded in
the Phase 6 operations review.

## 10. Immediate next action

The non-secret pilot decisions in this guide have been supplied. Do not send the Heroku key in chat; it
must remain in the ignored botq `backend/.env`.

```text
Inference provider: heroku
Pilot repository SSH URL: git@github.com:cosq-network/botq-dev-pilot-1.git
Pilot branch: main
Preview target: local-only
Deployment target: local Docker Compose
SLA / RPO / RTO: 99.5% / 24 hours / 8 hours
Repository commit: 31cbdb1
```

The next action is to verify `backend/.env`, run the preflight in Section 4, configure the API automation
principal/policy, and connect the initialized repository through botq. Leave the implementation provider
disabled until the provider preflight and Gates 2/3 approvals pass. Then start Gate 1 and the
requirements/architecture workflow. Credentials can be provided through the local ignored `.env` or the
deployment platform's secret manager; they should not be sent in chat.
