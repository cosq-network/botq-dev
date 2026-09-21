# Phase 4 Design and Acceptance Runbook

**Status:** Control-plane foundation implemented and the local-only BotQ preview has passed its automated
HAT workflow. For the API-only pilot, automated acceptance/accessibility evidence may satisfy Gate 5
when the project policy explicitly records that choice. The external HTTPS preview adapter path is
intentionally not being exercised for this pilot.

This document describes the Phase 4 slice currently implemented in botq. It is an operator guide,
not a replacement for the requirements baseline in
`AI_Software_Delivery_Platform_SRS.docx` or the delivery sequence in
`IMPLEMENTATION_ROADMAP.md`.

## Scope delivered

The Phase 4 control plane now supports:

- Versioned mockup artifacts bound to an approved architecture version and content hash.
- Penpot file references, optional read-only metadata retrieval, page/node links to work items,
  anchored comments, and explicit human handoff when Penpot write/comment capability is absent.
- Mockup submission and approval using the existing immutable version + hash approval semantics.
- Preview records pinned to a mockup hash and commit SHA, with authenticated access, non-production
  data policy, evidence, and an expiry boundary.
- Acceptance sessions with scenario guidance and per-criterion `pass`, `fail`, `blocked`, or
  `na` results.
- Defect triage with severity, reproduction steps, expected/actual behavior, attachments, and
  regression evidence. Defects requiring regression tests cannot be closed without a passed result.

## API surface

All endpoints require an authenticated organization-scoped token.

| Workflow | Endpoints | Required scopes |
|---|---|---|
| Mockups | `/api/v1/design/mockups` and child routes | `design:read`, `design:write`, `approval` for review decisions |
| Penpot preview metadata | `/api/v1/design/mockups/{id}/preview` | `design:read` |
| Preview deployments | `/api/v1/design/previews` and `/revoke` | `preview:read`, `preview:write` |
| Acceptance | `/api/v1/design/acceptance/sessions` and child routes | `acceptance:read`, `acceptance:write` |
| Defects | `/api/v1/design/defects` and child routes | `defect:read`, `defect:write` |

## Required workflow

1. Approve the requirement baseline and architecture package.
2. Create a mockup with the Penpot `file_id` and optional file/preview URLs.
3. Add page/node-to-work-item links and resolve open design comments.
4. Submit the mockup and obtain an approval from a reviewer who is not its author.
5. Create a preview using the approved mockup, the deployed commit SHA, an authenticated access
   policy, synthetic/non-production data, and an expiry timestamp.
6. Create an acceptance session with scenario guidance and explicit criteria.
7. Record evidence for every criterion. A session is accepted only when all criteria pass or are
   marked `na`, and no critical/high defect remains open.
8. Create defects for failed or blocked behavior. Remediation must include regression evidence;
   policy-selected verification then closes or reopens the defect.

## Recorded local pilot evidence

The local Docker preview at `http://127.0.0.1:8000` passed automated HTTP HAT for valid registration,
duplicate registration rejection, password mismatch rejection, valid login/dashboard access, logout,
and sixth-failed-login rate limiting. The botq workbench accessibility baseline also passed. These are
supporting automated results. Keyboard-only, screen-reader, 200% zoom/reflow, contrast, reduced-motion,
and error-recovery review remain useful optional evidence when the project policy requires or requests
manual acceptance.

## Penpot configuration

The adapter is intentionally read-only. Configure it through environment variables; do not put
tokens in project records, mockup content, prompts, or logs:

```text
PENPOT_API_BASE_URL=https://<penpot-host>
PENPOT_API_TOKEN=<read-only-token>
PENPOT_FILE_PATH=/api/files/{file_id}
PENPOT_API_TIMEOUT_SECONDS=15
```

The file path is configurable because Penpot API routes vary by deployment/version. If the adapter
is unavailable, botq returns a documented human handoff. It never claims that it edited a Penpot
file or created a Penpot comment.

## Operator workbench

Open `/workbench` on the same origin as the API. The workbench stores the bearer token only in
browser session storage and uses the existing authenticated API. It supports mockup and Penpot-
reference review, protected preview launch, acceptance-session creation, per-criterion
Pass/Fail/Blocked/N-A recording, and defect triage with regression evidence.

The workbench does not create fake previews, edit Penpot files, bypass approval, or substitute
unverified assertions for Gate 5 evidence. Preview URLs must be supplied by an approved
non-production deployment process.

## Preview deployment adapter

To provision a preview through an approved host, set `PREVIEW_DEPLOYMENT_URL` and
`PREVIEW_DEPLOYMENT_TOKEN`, then call `POST /api/v1/design/previews` with `deploy: true` instead
of supplying `url`. The adapter sends the approved mockup version/hash, optional approved change
set, commit SHA, environment, access policy, and expiry to the HTTPS webhook. The webhook must
return:

```json
{"url":"https://preview.example/run/123","deployment_id":"deploy-123","evidence":{}}
```

The response URL must be HTTPS; invalid responses fail the request and no preview record is
created. The provider is responsible for authentication, synthetic/non-production data, and
actually deploying the commit. `GET /api/v1/design/previews/<id>` exposes the resulting immutable
binding for acceptance evidence.

## Phase 2/3 operational prerequisites

The Phase 2/3 control plane is implemented. Gates 2/3 and 4 still require real synchronized or submitted
pilot evidence:

- The agreed pilot uses Heroku Managed Inference with model `nova-2-lite`.
- Configure the Heroku credential only through the ignored botq `backend/.env` or a deployment secret store.
- Connect `git@github.com:cosq-network/botq-dev-pilot-1.git` on `main` over the validated SSH Git adapter.
- Run the approved plan through the database-leased `AgentRunWorker` in the Linux Docker sandbox.
- Provide `environment.branch` and `environment.base_commit` on the run; the worker persists a
  draft change set and checkpoint, and verification evidence must bind to its exact `diff_hash`.
- Collect passing test, security-scan, reproducibility, commit, image, lockfile, and environment
  manifest evidence before approving the change set.

Provider selection is configured with `REQUIREMENT_ANALYSIS_PROVIDER=runpod`, `heroku`, or an
ordered fallback such as `heroku,runpod`. See the provider section in the root `README.md` for
the complete variable list.

## Gate 5 evidence checklist

The following evidence is required before Phase 4 can exit at Gate 5:

- Approved mockup version and content hash.
- Preview URL, environment label, expiry, access policy, mockup hash, and commit SHA.
- Acceptance session with evidence for every criterion.
- All blocking defects closed with passed regression evidence or an authorized waiver.
- Product owner, designer, and QA sign-off recorded in the audit trail, or API automation decisions when
  the selected policy permits automated acceptance.
- Preview revoked or expired after the acceptance window.

For this pilot, local acceptance may be performed against the local Docker Compose application, but it
must be explicitly recorded as a pilot-scope deviation because it does not prove the HTTPS preview
adapter contract. The Penpot/design reference is also not yet supplied. A full Gate 5 exit still needs
the approved mockup/design evidence, HAT results, automated accessibility/acceptance evidence or a
policy-selected manual review, defect disposition, and explicit API decisions; none may be represented
by simulated success.
