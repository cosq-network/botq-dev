# botq Pilot Status

**Status date:** 2026-09-20  
**Overall status:** Repository-side implementation, local technical exercises, and the API-only
gate-control surface are substantially complete. Linux CI-equivalent checks, Dockerized API E2E,
checkpoint recovery, concurrent load, Redis shared limiting, Prometheus/alert validation, retention,
local Compose deploy/rollback, and the seven-gate API now have fresh evidence. Pilot gates remain open
only where real provider, submitted evidence, or production-environment evidence has not yet been
recorded through the API.

## Confirmed pilot profile

| Item | Decision |
| --- | --- |
| Pilot repository | git@github.com:cosq-network/botq-dev-pilot-1.git |
| Branch | main |
| Repository commit | 31cbdb1 |
| GitHub host-key fingerprint | SHA256:qQSTyn6li7lXUuoTW1WA3hWCoh4wn4WGKvu6JYYs3cM |
| Inference | Heroku managed inference |
| Model | nova-2-lite |
| Preview | Local-only |
| Deployment | Local Docker Compose |
| SLA / RPO / RTO | 99.5% / 24 hours / 8 hours |
| Feature | Registration and login |
| Stack | Python Flask + PostgreSQL, server-rendered templates |
| Security scope | Argon2id, CSRF, secure sessions, 12-character passwords, logout, rate limiting |
| Out of scope | Email verification, password reset, MFA, external preview |
| Gate approval mode | API automation pilot (`api_automation`) |
| Automation principal | Dedicated organization user with least-privilege project/gate roles |

The Heroku endpoint and key are configured in the local ignored botq backend environment. The key is
not recorded in this document or committed to source control.

## Completion matrix

| Area | Status | Evidence or remaining action |
| --- | --- | --- |
| botq Phase 1 foundation | Complete repository-side | Existing Phase 1 tests and real SSH adapter validation |
| botq Phase 2/3/4 control plane | Implemented and exercised | Baseline, architecture, plan, agent-run, change-set, preview, acceptance, and defect APIs are implemented; Gate 4 still needs a valid persisted change set and hash-bound evidence |
| botq Phase 5 release controls | Implemented; final evidence pending | Local Compose adapter deploy/health and explicit previous-definition rollback are implemented; immutable image ID, dependency SBOM, and checksums recorded; release/deployment records must be submitted as gate evidence |
| botq Phase 6 hardening foundation | Implemented and exercised locally | Linux scans/tests, checkpoint recovery, 32-concurrency load, Redis shared limiting, Prometheus/alerts, retention dry-run/execution, and security baseline passed; production-scale evidence must be submitted before production readiness is claimed |
| Pilot Flask application | Complete | Initialized and pushed to main as commit 31cbdb1 |
| Pilot application tests | Complete | 8 pytest tests passed; Ruff and compile checks passed |
| botq automated validation | Complete | Full backend pytest suite passed (`156 passed`); Ruff and compileall passed; Dockerized HTTP API E2E suite passed 10 tests |
| Pilot Docker runtime | Deployed locally | PostgreSQL migration applied; local preview health and rollback/restore health returned `ok` |
| Gate 1 repository onboarding | Complete | botq project and repository record created; GitHub host fingerprint verified; deploy key authorized; botq connection test passed; `main` synchronized at commit `31cbdb1e31a120c0f90ce2e8c638957e2ba68aeb` |
| Gate 2 requirements | Technical approval recorded | Baseline `aeab2014-bf03-4303-9afb-2ec6087fa684`, hash `729c6f5c...38548`, Heroku analysis completed, 19 proposals applied, separate reviewer approval recorded |
| Gate 3 architecture/planning | Technical approval recorded | Architecture `c27b8831...8046f` and plan `56823201...71c3d` approved and hash-bound; further attestation is policy-governed |
| Gate 4 managed inference | Evidence incomplete | Prior Heroku attempts are recorded and rejected where invalid; a valid persisted change set, tests/scans bound to its hash, provider usage/cost or explicit unavailability, reproducibility evidence, and API automation decision are still needed |
| Gate 5 UI/UX and acceptance | Automated local acceptance passed | Six HTTP HAT criteria passed and botq automated accessibility baseline passed; API-only pilot may record automated acceptance evidence, while any manual review remains optional policy evidence |
| Gate 6 release/deployment | Local package controls passed; API evidence pending | Local Compose deploy/health and explicit previous-definition rollback are implemented; release/deployment evidence must be submitted or synchronized, then approved through the selected policy |
| Gate 7 hardening | Local evidence passed; API evidence pending | Linux CI-equivalent checks passed; 32-concurrency local load had zero errors and p95 `157.863 ms`; checkpoint recovery, Redis sharing, Prometheus/alerts, and retention passed locally; production topology/scale and alert-delivery evidence are still needed for production readiness |

**Hardening extension completed repository-side:** optional Redis shared limiting, local Compose
deployment adapter, retention execution, Prometheus/Grafana templates, alert-rule validation, CI
evidence artifacts, and release-evidence manifest/SBOM/checksum generation are implemented and locally
exercised. They still require target-environment configuration and submitted operational evidence
before they satisfy Gates 6–7.

The API-first gate-control sequence is documented in
[`API_GATE_CONTROL_GUIDE.md`](API_GATE_CONTROL_GUIDE.md).

Project-specific responsibility assignment is now API-enabled. Organization users and roles can also
be created and managed through authorized APIs. Configure primary and backup users, effective dates,
and responsibility types through the endpoints documented in that guide; enable
`require_project_responsibility_assignment` when the pilot is ready to require the assigned principal
for each review. The API enforces tenant scope, role-to-responsibility checks, and audit logging.

The explicit seven-gate control API is also implemented. It provides gate listing, evidence
submission, readiness evaluation, responsibility decisions, closure, reopening, and audit history.

## Recorded evidence and remaining work

No additional secret values should be sent in chat. The remaining work is execution and submitted
evidence:

- bind tests/scans/reproducibility evidence to the exact future valid Heroku change-set hash, then record the API automation decision;
- record Gate 5 automated acceptance/accessibility evidence and any optional manual review evidence selected by policy;
- create or synchronize the botq release and deployment-plan records, or configure an approved HTTPS deployment provider for `execute=true`;
- configure the intended production topology, run production-scale concurrency and checkpoint restart, configure alert delivery, and record Security/Operations readiness evidence/decision through the API.

Evidence files are kept in the ignored local `.pilot-evidence/` directory and contain no provider keys.
The provider usage/cost capture path is implemented, but the completed Heroku response supplied no usage
or cost object; actual billing evidence must come from the Heroku account/gateway if required.

## Recommended next sequence

1. Rerun the approved Heroku implementation plan with the corrected repository-grounded prompt and require a valid self-review/change set.
2. Run pilot tests/scans against that exact change-set contents; attach hashes, provider usage/cost, and reproducibility results.
3. Submit or synchronize Gate 5 acceptance/accessibility evidence under the selected automated policy.
4. Create/approve the botq release and deployment plan through the API, then execute the local deployment adapter or configure an HTTPS provider.
5. Complete production-scale load, live alert-delivery, and Security/Operations readiness evidence, then close gates through the API.

Until these steps produce evidence, botq should be described as repository-side implemented with a
substantially exercised pilot—not as a completed production-ready platform.
