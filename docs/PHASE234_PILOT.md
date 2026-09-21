# Phase 2–4 Pilot Execution Runbook

**Status:** Local control-plane and safety validation implemented; the agreed BotQ Pilot application is
initialized and smoke-tested, but botq's external/live pilot execution remains required. See
`docs/PILOT_STATUS.md` for the current completion matrix.

This runbook closes the repository-side preparation for Gates 2, 3, 4, and 5. It does not fabricate
provider, repository, preview-host, Penpot, manual-review, or automation-decision evidence.

## 1. Local preflight

Run from the repository root:

```powershell
$env:PYTHONPATH = (Resolve-Path backend).Path
& .\backend\.venv\Scripts\python.exe scripts\validate_provider_config.py --json
& .\backend\.venv\Scripts\python.exe scripts\validate_accessibility.py --json
& .\backend\.venv\Scripts\python.exe -m pytest backend/tests/test_phase23_execution.py backend/tests/test_phase4_adapters.py -q
& .\backend\.venv\Scripts\python.exe -m ruff check backend/app backend/tests scripts
& .\backend\.venv\Scripts\python.exe -m ruff format --check backend/app backend/tests scripts
git diff --check
```

The provider preflight never prints secret values and never makes a network call.

## 2. Provider selection

Select one provider or an ordered fallback. The same credentials are used by requirement analysis
and the Phase 3 implementation worker:

```text
# Heroku Managed Inference
REQUIREMENT_ANALYSIS_PROVIDER=heroku
AGENT_IMPLEMENTATION_PROVIDER=heroku
HEROKU_INFERENCE_BASE_URL=https://<managed-inference-host>
HEROKU_INFERENCE_KEY=<secret-store-reference>
HEROKU_INFERENCE_MODEL=<approved-model>
HEROKU_INFERENCE_MAX_TOKENS=4096

# RunPod Serverless
REQUIREMENT_ANALYSIS_PROVIDER=runpod
AGENT_IMPLEMENTATION_PROVIDER=runpod
RUNPOD_API_KEY=<secret-store-reference>
RUNPOD_ENDPOINT_ID=<endpoint-id>

# Ordered fallback
REQUIREMENT_ANALYSIS_PROVIDER=heroku,runpod
AGENT_IMPLEMENTATION_PROVIDER=heroku,runpod
```

`RUNPOD_INFERENCE_URL` is optional and defaults to the RunPod `runsync` endpoint. All configured
provider URLs must be HTTPS. Credentials belong in the deployment secret store, never in project
records, prompts, logs, or source control.

For the agreed pilot, use Heroku managed inference with model `nova-2-lite` and the configured
`https://us.inference.heroku.com` base URL. The Heroku key must remain in the ignored `backend/.env`.
The adapter sends `max_tokens=4096` by default so structured responses are not truncated; adjust this
only through the runtime environment after validating provider limits.
For a local/Compose pilot, copy `backend/.env.example` to `backend/.env` and set the variables
shown above. Do not commit `backend/.env` or paste its secret values into chat. For production,
inject the same variable names through the host/platform environment or external secret manager;
the application receives the actual values only at runtime.

## 3. Gate 2/3 execution

1. Connect `git@github.com:cosq-network/botq-dev-pilot-1.git` on `main` through the SSH adapter with
   the recorded host-key fingerprint. The repository is initialized at commit `31cbdb1`.
2. Create and analyze the registration/login requirement baseline.
3. Resolve or formally waive all blocking findings.
4. Apply and review generated work items.
5. Create architecture, ADRs, threat/failure controls, and trace links.
6. Record the configured product-owner and architecture-review decisions through the API.

Required evidence: baseline version/hash, analysis provider/prompt/policy provenance, finding
resolution history, work-item tree, architecture/ADR version/hash, traceability, and audit events.

## 4. Gate 4 execution

1. Create a technical plan from the approved architecture.
2. Include the typed environment manifest, budget, tools, writable paths, escalation rules, and
   feasibility checks.
3. Approve the plan and create an agent run with `environment.branch` and
   `environment.base_commit`.
4. Start the database-leased worker in the Linux Docker environment.
5. Inspect the draft change set and self-review; the worker never applies model output directly.
6. Run tests and required dependency, secret, license, SAST, and image scans.
7. Record verification evidence bound to the exact change-set hash, then record the policy-selected
   code/QA approval decision.

The worker stops safely if paused, cancelled, its plan changes, its writable boundary is exceeded,
or its database lease is lost. A provider failure is observable as a failed run; it is not reported
as a successful change set.

## 5. Gate 5 execution

1. Configure the read-only Penpot adapter and link the pilot mockup to work items.
2. Resolve design comments, submit the mockup, and obtain designer/product-owner approval.
3. Provision a non-production HTTPS preview through the approved deployment webhook, or supply a
   verified HTTPS URL manually. The preview must pin the approved mockup hash and commit SHA.
4. Run HAT with explicit criteria and evidence for every result.
5. Log defects; do not close a regression-required defect without passed regression evidence.
6. Reopen any defect that fails human verification.
7. Revoke or allow the preview to expire, then record product-owner, designer, and QA decisions or the
   policy-selected automation approval.

Required evidence: mockup version/hash, Penpot references, preview deployment response, access/data
policy, expiry, commit SHA, HAT criteria/results/evidence, defect and regression history, and the
final audit trail.

## 6. What remains external

The following remain to be completed through the control plane and cannot be claimed from the pilot
application repository alone:

- credentials and live health checks for Heroku Managed Inference and/or RunPod;
- botq project registration, repository connection/sync, and the Linux Docker execution host;
- a real Penpot instance and designer review;
- a real non-production preview host;
- policy-selected HAT/accessibility evidence and explicit API approval decisions.

Once those prerequisites are supplied, this runbook provides the sequence and evidence boundary for
closing Gates 2–5 without weakening the approval controls.
