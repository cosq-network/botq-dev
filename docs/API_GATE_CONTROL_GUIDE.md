# botq API Gate Control Guide

## The important idea

Gate control means an authorized caller or explicitly configured automation principal records evidence
and decisions through the API. It does not mean anyone edits the database or performs an unrecorded
manual step. All operational state changes use this API path:

```text
Evidence is reviewed or produced
        ↓
Authorized client sends an API request
        ↓
botq validates authorization, state, hashes, and segregation of duties
        ↓
botq records the decision and audit event
```

The API-only controlled workflow uses the same audit/evidence boundary, but the decision-maker is a dedicated
automation principal selected by project gate policy:

```text
Evidence is synchronized or submitted
        ↓
Authorized automation principal sends an API approval request
        ↓
botq validates authorization, policy, state, hashes, and gate ordering
        ↓
botq records the decision and audit event
```

The authorized client may be the botq web UI, `curl`, Postman, a project CLI, or another approved
integration. User accounts and automation principals must have separate tokens; do not share tokens
between reviewers or automation jobs.

## Before starting

1. Create a botq account for each reviewer or automation principal.
2. Obtain a bearer token through the approved login flow.
3. Identify the project ID and artifact/release/version hashes.
4. Collect the evidence files or URLs to attach to decisions.
5. Configure organization/project gate policy and project-specific responsibility assignments if
   the policy requires them.

Example authorized-client request:

```bash
export BOTQ_URL="http://127.0.0.1:8886"
export BOTQ_TOKEN="<token from the authorized reviewer login>"
curl -sS "$BOTQ_URL/api/v1/organizations/me" \
  -H "Authorization: Bearer $BOTQ_TOKEN"
```

Never put real tokens or provider keys in this document, Git, evidence JSON, prompts, or chat.

## Gate policy and automation mode

Gate policy is configured at organization scope and can be overridden per project:

```text
GET   /api/v1/organizations/me/gate-policy
PATCH /api/v1/organizations/me/gate-policy
GET   /api/v1/projects/{project_id}/gate-policy
PATCH /api/v1/projects/{project_id}/gate-policy
```

The default policy is conservative:

```json
{
  "approval_mode": "human_api",
  "require_gate_decisions": true,
  "require_project_responsibility_assignment": true,
  "allow_waivers": true,
  "require_previous_gate_closed": true,
  "auto_sync_evidence": true
}
```

Supported approval modes:

| Mode | Meaning |
| --- | --- |
| `human_api` | Assigned human users record API decisions. |
| `api_automation` | A dedicated automation principal records explicit API decisions for controlled automation. |
| `disabled` | Evidence-only closure; use only when deliberately configured. |

For a controlled automation workflow, configure `api_automation`, create a dedicated automation user with the
`gate_automation` role, assign only the project responsibilities needed for the selected gates, and
record every decision through `auto-approve` or
`decisions`. The automation principal is still a normal organization user for audit and tenant
isolation purposes, with `user_type: "automation"`.

## Organization users, roles, and reviewer enforcement

An organization administrator or configuration manager can manage project participants through the API:

```bash
# Create an organization user and assign organization-level capabilities.
curl -X POST "$BOTQ_URL/api/v1/organizations/me/users" \
  -H "Authorization: Bearer $CONFIG_MANAGER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"email":"qa@example.test","display_name":"QA Reviewer", \
       "password":"<temporary-password-at-least-12-chars>","roles":["qa_engineer"]}'

# Create a least-privilege automation principal for controlled API automation.
curl -X POST "$BOTQ_URL/api/v1/organizations/me/users" \
  -H "Authorization: Bearer $CONFIG_MANAGER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"email":"gatebot@example.test","display_name":"Gate Automation", \
       "password":"<temporary-password-at-least-12-chars>", \
       "roles":["gate_automation"],"user_type":"automation"}'

# Replace the user’s organization roles.
curl -X PUT "$BOTQ_URL/api/v1/organizations/me/users/$USER_ID/roles" \
  -H "Authorization: Bearer $CONFIG_MANAGER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"roles":["qa_engineer"]}'

# Enable project-responsibility enforcement for older approval APIs if desired.
curl -X PATCH "$BOTQ_URL/api/v1/organizations/me/settings" \
  -H "Authorization: Bearer $CONFIG_MANAGER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"enforce_project_responsibilities":true}'
```

Use `GET /api/v1/organizations/me/users` to discover existing users. Organization roles provide
API capabilities; project responsibility assignments identify which person may perform a specific
project review. Gate policy uses `require_project_responsibility_assignment`; older artifact approval
APIs use the organization `enforce_project_responsibilities` setting. When enforcement is enabled,
botq requires the active primary project assignee for the relevant artifact or gate responsibility.
The assignment names are intentionally separate from role names: for example, `qa_reviewer` is
normally paired with the organization role `qa_engineer`.

The user-creation API accepts a temporary password because botq does not send email invitations itself.
Use an approved secure client or identity-provider workflow to deliver/reset that password. Never
place it in source control or shared logs.

## Explicit gate control API

Each project has seven API-managed gate records. Gate evidence and decisions are separate from the
underlying requirements, architecture, release, and deployment artifacts, so an authorized client can
query or operate the gate lifecycle directly:

```text
GET  /api/v1/projects/{project_id}/gates
GET  /api/v1/projects/{project_id}/gates/summary
GET  /api/v1/projects/{project_id}/gates/{gate_number}
POST /api/v1/projects/{project_id}/gates/{gate_number}/sync
POST /api/v1/projects/{project_id}/gates/{gate_number}/evidence
POST /api/v1/projects/{project_id}/gates/{gate_number}/evaluate
POST /api/v1/projects/{project_id}/gates/{gate_number}/decisions
POST /api/v1/projects/{project_id}/gates/{gate_number}/auto-approve
POST /api/v1/projects/{project_id}/gates/{gate_number}/close
POST /api/v1/projects/{project_id}/gates/{gate_number}/reopen
GET  /api/v1/projects/{project_id}/gates/{gate_number}/history
```

Evidence uses `not_run`, `passed`, `failed`, `waived`, `not_applicable`, or `blocked`. Missing checks
are serialized as `blocked`; they are never silently treated as passed. Closing is rejected until all
required evidence passes (or is explicitly waived/not applicable), required decisions are present under
the selected policy, evidence is unexpired, and any sequential previous gate is closed. Closing and
reopening are audited.

`sync` derives evidence only from botq records and configured adapters. For everything else, submit
external evidence with a source, command/API operation, timestamp, result, and content hash:

```bash
curl -X POST "$BOTQ_URL/api/v1/projects/$PROJECT_ID/gates/4/evidence" \
  -H "Authorization: Bearer $CONFIG_MANAGER_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: gate4-tests-$CHANGE_SET_HASH" \
  -d '{"key":"tests_bound_to_change_set_hash","status":"passed", \
       "source":"ci","command":"python -m pytest", \
       "content_hash":"<sha256-evidence-hash>", \
       "evidence":{"change_set_hash":"<hash>","result":"passed"}}'
```

For controlled API automation, the automation principal records approvals explicitly:

```bash
curl -X POST "$BOTQ_URL/api/v1/projects/$PROJECT_ID/gates/4/auto-approve" \
  -H "Authorization: Bearer $GATE_AUTOMATION_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: gate4-auto-approval" \
  -d '{"comment":"All configured Gate 4 checks passed."}'
```

The same sequence can be run end to end with `scripts/run_api_gate_lifecycle.py`. Supply a real
evidence manifest for controlled evidence; `--synthetic-evidence` exists only for local API contract tests:

```bash
python scripts/run_api_gate_lifecycle.py \
  --project-id "$PROJECT_ID" \
  --evidence-manifest .evidence/gates.json
```

The manifest shape is:

```json
{
  "gates": {
    "4": {
      "checks": {
        "tests_bound_to_change_set_hash": {
          "status": "passed",
          "source": "ci",
          "command": "python -m pytest",
          "content_hash": "<sha256>",
          "evidence": {"change_set_hash": "<hash>", "result": "passed"}
        }
      }
    }
  }
}
```

## Project-specific responsibility assignments

The person responsible for each activity is selected per project. These are responsibility types, not
universal people:

| Responsibility type | Decision responsibility | API action from the authorized client |
| --- | --- | --- |
| Product Owner | Scope and acceptance | Submit/approve requirements and acceptance |
| Architecture Reviewer | Architecture | Approve architecture package/ADR |
| Developer | Change quality | Approve or reject change set |
| QA Reviewer | Verification | Approve tests, scans, and acceptance evidence |
| Designer | Design, when applicable | Approve mockup or request changes |
| Release Manager | Release/deployment | Approve release and deployment plan |
| Security Approver | Security risk | Approve security evidence and deployment risk |
| Operations Approver | Operational readiness | Approve monitoring, recovery, alerts, and readiness |

The implementation has both organization-scoped role APIs and a project-scoped
responsibility-assignment API. Assignment writes require `config:manage`; reads require `config:read`.
Assignments are tenant-scoped, support effective dates and primary/backup users, apply the configured
segregation-of-duties rules, and create audit events.

The API is:

```text
GET    /api/v1/projects/{project_id}/responsibility-assignments
POST   /api/v1/projects/{project_id}/responsibility-assignments
PATCH  /api/v1/projects/{project_id}/responsibility-assignments/{assignment_id}
```

Example configuration through an authorized client:

```bash
curl -X POST "$BOTQ_URL/api/v1/projects/$PROJECT_ID/responsibility-assignments" \
  -H "Authorization: Bearer $CONFIG_MANAGER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"user_id":"<developer-user-id>","responsibility_type":"developer", \
       "is_primary":true,"effective_from":"2026-09-20T00:00:00Z"}'

curl "$BOTQ_URL/api/v1/projects/$PROJECT_ID/responsibility-assignments?as_of=2026-09-20T00:00:00Z" \
  -H "Authorization: Bearer $CONFIG_REVIEWER_TOKEN"
```

Use another assignment with `is_primary:false` as a backup, and use `effective_until` when a
responsibility ends. The default segregation groups prevent one user from simultaneously being the
primary Developer and QA Reviewer, or Release Manager and Security Approver, during overlapping dates.
An archived project cannot receive new or changed assignments.

## Gate 2 — requirements

Authorized caller under policy: review the baseline, findings, work items, acceptance expectations,
and scope; decide approve, request changes, reject, waive, or cancel.

Authorized-client API examples:

```bash
curl -X POST "$BOTQ_URL/api/v1/requirements/baselines/$BASELINE_ID/submit" \
  -H "Authorization: Bearer $BOTQ_TOKEN"

curl -X POST "$BOTQ_URL/api/v1/requirements/baselines/$BASELINE_ID/approve" \
  -H "Authorization: Bearer $BOTQ_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"comment":"Scope and acceptance criteria reviewed."}'
```

The decision is bound to the current baseline version/hash. A changed baseline requires new approval.

## Gate 3 — architecture and technical plan

Authorized caller under policy: review architecture, ADRs, security boundaries, provider choice,
repository access, permissions, risks, rollback, and validation commands.

```bash
curl -X POST "$BOTQ_URL/api/v1/architecture/packages/$ARCHITECTURE_ID/approve" \
  -H "Authorization: Bearer $ARCHITECTURE_TOKEN"

curl -X POST "$BOTQ_URL/api/v1/plans/$PLAN_ID/approve" \
  -H "Authorization: Bearer $PLAN_TOKEN"
```

The client receives a success/error response and botq records the approval and audit event.

## Gate 4 — managed inference and change set

Authorized caller under policy: inspect the generated diff, verify paths and repository grounding,
review tests/scans, reproducibility and provider cost, then record Developer/QA decisions.

```bash
curl -X POST "$BOTQ_URL/api/v1/change-sets/$CHANGE_SET_ID/submit" \
  -H "Authorization: Bearer $DEVELOPER_TOKEN"

curl -X POST "$BOTQ_URL/api/v1/change-sets/$CHANGE_SET_ID/approve" \
  -H "Authorization: Bearer $QA_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"comment":"Exact-hash tests and scans reviewed."}'
```

Do not apply an unapproved change set. If the provider returns no cost object, record that fact and
attach billing evidence if policy requires it.

## Gate 5 — UI/UX and acceptance

Authorized caller under policy: record HAT/accessibility/acceptance evidence, each criterion and
defect, and decide whether acceptance is complete. For controlled API automation, automated accessibility can
satisfy Gate 5 only when the policy and evidence explicitly state that automated acceptance was chosen.

```bash
curl -X POST "$BOTQ_URL/api/v1/design/acceptance/sessions/$SESSION_ID/results" \
  -H "Authorization: Bearer $QA_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"criterion_key":"keyboard-navigation","outcome":"pass","evidence":{"notes":"All controls reachable."}}'

curl -X POST "$BOTQ_URL/api/v1/design/acceptance/sessions/$SESSION_ID/complete" \
  -H "Authorization: Bearer $PRODUCT_OWNER_TOKEN"
```

Use the defect APIs to record reproduction steps and regression evidence. Penpot and external preview are
optional for this local-only workflow; record that scope decision through the approved project decision
process or gate evidence.

## Gate 6 — release, deployment, and rollback

Authorized caller under policy: review image digest, SBOM, checksums, commit, migrations, readiness,
and rollback; approve the release and deployment plan through the required policy path; review health
and authorize rollback if needed.

```bash
curl -X POST "$BOTQ_URL/api/v1/releases" \
  -H "Authorization: Bearer $RELEASE_MANAGER_TOKEN" \
  -H "Content-Type: application/json" -d @release.json

curl -X POST "$BOTQ_URL/api/v1/releases/$RELEASE_ID/readiness" \
  -H "Authorization: Bearer $RELEASE_MANAGER_TOKEN" \
  -H "Content-Type: application/json" -d @readiness-evidence.json

curl -X POST "$BOTQ_URL/api/v1/releases/$RELEASE_ID/approve" \
  -H "Authorization: Bearer $RELEASE_MANAGER_TOKEN"

curl -X POST "$BOTQ_URL/api/v1/deployment-plans" \
  -H "Authorization: Bearer $RELEASE_MANAGER_TOKEN" \
  -H "Content-Type: application/json" -d @deployment-plan.json

curl -X POST "$BOTQ_URL/api/v1/deployment-plans/$PLAN_ID/approve" \
  -H "Authorization: Bearer $SECURITY_TOKEN"

curl -X POST "$BOTQ_URL/api/v1/deployments" \
  -H "Authorization: Bearer $RELEASE_MANAGER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"deployment_plan_id":"<plan-id>","execute":true}'

curl -X POST "$BOTQ_URL/api/v1/deployments/$DEPLOYMENT_ID/rollback" \
  -H "Authorization: Bearer $RELEASE_MANAGER_TOKEN"
```

For this controlled deployment workflow, configure `LOCAL_COMPOSE_FILE`, `LOCAL_COMPOSE_ROLLBACK_FILE`, and
`LOCAL_DEPLOYMENT_HEALTH_URL` through ignored `backend/.env`. A restart is not a rollback; the
rollback definition must identify the previous deployable release.

## Gate 7 — security and operations readiness

Authorized caller under policy: review security, threat model, tenant isolation, sandbox, dependency,
secrets, production-scale load, worker restart/checkpoint recovery, backup/restore, RPO/RTO, metrics,
alerts, retention, and provider cost evidence. Confirm the on-call destination received a real alert.
Decide approve, reject, or waive with expiry.

The technical evidence is collected by scripts and platform integrations. The decision must be sent by
the authorized client to the applicable readiness/approval API and recorded by botq. Do not mark the
gate complete by editing a document alone.

## Secrets and completion

Use `backend/.env` for local secrets or the deployment platform’s secret manager. Use
`backend/.env.example` as the template. Never commit `.env`, paste keys into chat, or place secrets in
prompts, screenshots, evidence JSON, or release records.

The controlled workflow is complete when every gate has technical evidence and the required policy decision has been
submitted through an authorized client and recorded by botq against the correct immutable version/hash.
Accountability lives in the policy-selected principal; API calls are the recording mechanism.
