# AI Software Delivery Platform - Implementation Roadmap

**Document Type:** Implementation Roadmap
**Version:** 2.6 (aligned to SRS v1.0)
**Status:** Repository-side Phase 2/3/4 implementation, Phase 5 release/deployment control plane, Phase 6 hardening foundation, and the explicit seven-gate API are implemented. Linux CI-equivalent checks, Dockerized API E2E, checkpoint recovery, concurrent load, Redis shared limiting, Prometheus/alert validation, retention, local Compose deploy/rollback, and API-only gate automation have been exercised. Gates 4–7 are not fully closed because valid change-set evidence, botq release/deployment records, production topology evidence, live alert delivery, and Security/Operations readiness evidence remain external or environment-specific. The execution runbook is [`PILOT_EXECUTION_GUIDE.md`](PILOT_EXECUTION_GUIDE.md), and the current completion matrix is [`PILOT_STATUS.md`](PILOT_STATUS.md).
**Date:** September 2026

**Latest repository-side hardening extension:** optional Redis-backed rate limiting, controlled
local-Compose deployment execution, confirmed/audited operational retention, Prometheus/Grafana
templates, alert-rule validation, CI verification artifacts, and release-evidence manifests/SBOM/checksums
are now available and locally exercised. They are disabled or non-production by default and still
require environment configuration, live delivery tests, and policy-selected API decisions to close Gates 6–7. The
API-first gate control is documented in [`API_GATE_CONTROL_GUIDE.md`](API_GATE_CONTROL_GUIDE.md).

---

## 1. Executive Summary

This roadmap implements the AI Software Delivery Platform defined in **AI_Software_Delivery_Platform_SRS v1.0 (2026-09-16)**: a browser-based multi-project control plane that coordinates AI software engineering agents under explicit human control. Every material transition - requirements, architecture, UI, plans, code, tests, releases, deployments - is recorded, reviewable, and gated by a person with the required role.

### 1.1 Objectives (SRS 1.1)
- Reduce manual effort required to decompose requirements and prepare engineering artifacts.
- Make AI decisions inspectable through evidence, diffs, logs, and approval history.
- Provide isolated, repeatable environments for code generation and verification.
- Preserve human authority over scope, design, production code, secrets, and deployment.
- Support greenfield and existing repositories without assuming a language or framework.

### 1.2 Success Measures (SRS 2.1)

| Measure | Target | How measured |
|---------|--------|--------------|
| Approval traceability | 100% of gated transitions have actor, time, decision, artifact version | Audit query |
| Reproducible verification | 100% of release candidates tested from pinned commit + immutable environment | Pipeline evidence |
| Production safety | 0 production deployments without approved plan + readiness result | Deployment policy check |
| Defect regression coverage | Every agent-remediated accepted defect has a reproducing test unless waived | Defect audit |
| Secret protection | 0 secret values returned through UI, logs, prompts, or API responses | Automated scans + security tests |
| Recovery readiness | Every production deployment records rollback instructions + prior deployable version | Release record |

**Supporting targets:** manual effort reduction ~60% for decomposition (SRS objective), control plane availability 99.5% monthly (NFR-01), project budget overruns < 10% (REQ-COM-08), user satisfaction > 4.5/5.

### 1.3 Timeline

| Phase | Duration | Target dates | Delivery gate |
|-------|----------|--------------|---------------|
| Phase 1: Foundation | 6 weeks | Weeks 1-6 | Secure project, repo cloned, diagnostic run |
| Phase 2: Requirements & Design | 7 weeks | Weeks 7-13 | Approved baseline + architecture (pilot repo) |
| Phase 3: Planning & Implementation | 8 weeks | Weeks 14-21 | Approved plan -> reviewable change set, tests pass |
| Phase 4: UI/UX & Acceptance | 6 weeks | Weeks 22-27 | Mockup, preview, HAT, remediation approved |
| Phase 5: Release & Deployment | 4 weeks | Weeks 28-31 | Pilot release deployed, post-deploy checks pass |
| Phase 6: Hardening | 4 weeks | Weeks 32-35 | Production readiness review approved |

**Total: 35 weeks (~8-9 months, Q3 2026 - Q2 2027)**

### 1.4 Preconditions to start production implementation (SRS Approval purpose, 19.3)

Production implementation and external pilot execution may begin only after:
1. Stakeholders approve the SRS baseline; and
2. All open decisions in Section 8 are resolved (decision owners and deadlines listed there).

The repository may continue development and control-plane implementation before those external
conditions are closed. Phase 2/3/4 repository-side controls and preflight evidence are delivered,
while Gates 2/3, 4, and 5 remain operational review gates requiring the pilot environment and
human decisions. The execution sequence is documented in `docs/PHASE234_PILOT.md`.

---

## 2. Scope (SRS 1.2 / 1.3)

**In scope:**
- Project onboarding and repository connection
- Requirement capture and hierarchical work item generation
- Architecture, technical planning, and UI/UX workflows
- Agent execution with tools, checkpoints, and policy-selected approvals
- Source code changes, automated tests, review, and remediation
- Human acceptance testing and defect workflows
- Packaging, version tagging, Docker image creation, deployment, diagnostics, and rollback planning
- Audit, notifications, access control, provider routing, cost and usage records

**Out of scope (initial release):**
- Unsupervised production deployments
- Direct storage of plaintext private keys, API keys, or production passwords in the database
- Replacement of legal, security, clinical, financial, or regulatory review
- General-purpose project accounting, payroll, or CRM
- Training foundation models from scratch
- Guaranteed correction of every test failure without escalation

---

## 3. Delivery Model: Lifecycle and Gates (SRS 4.1 - 4.3)

### 3.1 Lifecycle stages

| Stage | Entry condition | Human gate | Exit condition |
|-------|-----------------|-----------|----------------|
| Requirements | Project initialized | Approve generated backlog | All required work items approved |
| Architecture | Requirements baseline approved | Approve architecture version | Architecture approved |
| Interface design | Architecture approved + UI scope exists | Approve mockups and interactive UI | UI sign-off recorded or stage N/A |
| Technical plan | Design inputs approved | Approve implementation plan | Plan approved |
| Implementation | Plan approved + environment ready | Review staged change set | Required tests pass + code gate approved |
| Acceptance | Automated verification passed | Accept feature or report defect | Acceptance approved + blocking defects closed |
| Release | All readiness checks pass | Approve deployment plan | Release package created |
| Deployment | Deployment authorized | Optional production confirmation per policy | Health checks pass or rollback completes |

### 3.2 Approval semantics (SRS 4.2)
- Approval binds to an **immutable artifact version + content hash**; material modification creates a new version and invalidates downstream approvals per impact rules.
- Decisions: **Approve / Request changes / Reject / Waive / Cancel**. Waive requires reason, authorized role, and expiry or scope.
- Comments do not constitute approval; a completed review requires an explicit decision.
- Policies are configurable by project, artifact type, environment, and risk level. Timeouts notify but never auto-approve.
- **Segregation of duties:** an author of a release plan or deployment change cannot be its sole approver; automation satisfies approvals only when an explicit project policy selects an authorized automation principal.

### 3.3 End-to-end workflow (SRS 4.3)

Requirement intake → Work item review → Architecture review → Mockup review → Interactive UI review → Technical plan review → Implementation + self review → Automated verification → Human acceptance → Release readiness → Deployment plan review → Deployment + diagnostics.

A rejected gate returns to the owning stage. A defect returns to implementation with linked regression evidence.

---

## 4. Phase Plan Overview (SRS 20)

| Phase | Scope | Requirement coverage | Exit criteria |
|-------|-------|----------------------|---------------|
| 1 Foundation | Organizations, users, projects, PostgreSQL schema, audit, Git SSH, Docker runner, provider gateway | REQ-INF-01..07, REQ-COM-01, REQ-COM-02, REQ-COM-08 (record foundation), NFR-05/06 (base) | Secure project created; repo cloned; isolated diagnostic run completed |
| 2 Requirements & Design | Requirement intake, work items, review loops, architecture artifacts, traceability | REQ-REQ-01..06, REQ-DES-01..05, REQ-COM-03, REQ-COM-05, REQ-COM-07 | Approved baseline + architecture produced for a pilot repository |
| 3 Planning & Implementation | Repository analysis, plan gate, agent run control, diffs, tests, self-healing limits | REQ-PLN-01..05, REQ-IMP-01..07, REQ-COM-06, REQ-COM-08 | Approved plan generates reviewable change set + passing automated tests |
| 4 UI/UX & Acceptance | Penpot links, mockup review, preview deployment, HAT and defects | REQ-UI-01..05, REQ-QA-01..06 | Pilot feature passes mockup, preview, acceptance, remediation workflows |
| 5 Release & Deployment | Readiness, packaging, tags, images, deployment plan, diagnostics, rollback | REQ-REL-01..06, NFR-01 (operation) | Approved pilot release deploys + passes post-deployment checks |
| 6 Hardening | Security testing, performance, recovery, monitoring, retention, ops procedures | NFR-01..15, REQ-INF-07 (recovery), REQ-COM-04/08 | Production readiness review approved |

---

## 5. Detailed Phase Breakdown

### 5.1 Phase 1: Foundation - Weeks 1-6

| Week | Focus | Key tasks |
|------|-------|-----------|
| 1 | Project scaffold | Flask app factory + modular blueprints; config; repository, CI/CD (GitHub Actions); Docker Compose dev topology (Flask API, PostgreSQL, worker, reverse proxy) on one secured VPS (SRS 5.2) |
| 2 | Persistence | PostgreSQL schema + Flask-Migrate/Alembic for core entities (Organization, User, Role, Project, Repository Connection, Audit Event, Integration); tenant isolation (`org_id`); UTC timestamps; UUID identifiers (SRS 15.1/15.2) |
| 3 | Identity & RBAC | Authentication (OIDC with local dev fallback); SRS role model; organization/project/role/resource/action authorization; **audit service** - append-only, tamper-evident events with correlation IDs (REQ-COM-01/02) |
| 4 | Git adapter | Per-project SSH deploy keys, host-key verification, configurable default branch, RW/RO scope, connection test, credential rotation, clone/sync (REQ-INF-01, 16.3) |
| 5 | Secrets | Encrypted-at-rest store or external secret manager adapter; output masking; injection only into authorized jobs; forbidden from prompt context by default (REQ-INF-04) |
| 6 | Execution sandbox | Controlled Docker runner with allowlisted images, resource limits, network egress allowlists, workspace isolation; environment readiness job (REQ-INF-02/03/05/06); backup + restore baseline (REQ-INF-07) |

**Exit criteria / Gate 1:** Secure project created; a pilot repository is cloned; an isolated diagnostic environment run completes and reports versions, paths, disk, Docker status, network reachability. Owner: Infra Review Board (Tech lead + Security approver).

**Status (delivered):** All Phase 1 work items are implemented and validated on the Docker Compose / PostgreSQL stack - schema migration, bootstrap, login/RBAC, project + secret creation, sandbox readiness (`mandatory_ok`), isolated diagnostic run, image-allowlist denial, audit-chain verification (REQ-COM-01/02), and the backup/restore baseline (REQ-INF-07: `flask backup create|verify|restore`). The pilot-repository clone is now validated end-to-end against a **real** SSH Git remote via `scripts/validate_git.ps1` (deploy-key provisioning, host-key pinning, `ls-remote` test, clone, fetch/fast-forward sync, key rotation, revoke) using the actual `GitCommandBackend`. This surfaced and fixed three latent real-backend defects: `git()` not forwarding `env` (SSH commands were broken; only the fake backend had ever worked), `ssh-keygen` refusing to overwrite on rotation, and `sync` not fast-forwarding the local branch to the remote head (REQ-INF-01/16.3).

### 5.2 Phase 2: Requirements & Design - Weeks 7-13

| Week | Focus | Key tasks |
|------|-------|-----------|
| 7 | Requirement intake | Requirement Baseline entity: goals, specs, constraints, attachments, repo references, acceptance expectations; versioned + attributable (REQ-REQ-01) |
| 8 | Work items | Work Item hierarchy (Epic/Feature/Story/Task/Test Case); identifiers, descriptions, dependencies, acceptance criteria, priority, risk, traceability; circular dependency rejection (REQ-REQ-02/06) |
| 9 | AI generation & analysis | Deep Agents decomposition of approved input; coverage/consistency analysis - ambiguous, conflicting, duplicate, missing, untestable findings by severity (REQ-REQ-02/04) |
| 10 | Review & approval loop | Item + baseline review; Approve/Request changes/Reject/Waive/Cancel; approval binds to version + hash; findings block baseline approval; **change impact analysis** across downstream artifacts (REQ-REQ-03/05, 4.2) |
| 11 | Architecture generation | Context/component/data/integration/deployment/security/operational designs; versioned ADRs; existing-repo analysis; threat + failure analysis with controls, owners, verification (REQ-DES-01/03/04/05) |
| 12 | Design review loop | Anchored comments; revise-and-resubmit; new version preserves comment history + requires fresh approval; downstream artifacts bind to approved design hash (REQ-DES-02) |
| 13 | Traceability & plan gate | Requirement -> architecture traceability views; prompt/policy versioning (REQ-COM-07); search + relationships (REQ-COM-05); resolve Section 8 decisions before detailed design |

**Exit criteria / Gate 2 & 3:** Approved requirement baseline and approved architecture package for the pilot repository (Product owner -> Architecture Review Board). All mandatory work items approved; blocking findings = 0.

**Status (implemented control plane + approved local pilot artifacts):** Week 7 (requirement intake, REQ-REQ-01) is implemented and validated on the PostgreSQL stack - `RequirementBaseline` + immutable, hash-chained `RequirementBaselineVersion`, create/revise/compare/diff/submit endpoints scoped by `requirement:read`/`requirement:write`, tenant isolation, and audit events. Week 10 (approval loop, REQ-REQ-03 / SRS 4.2) is implemented: an append-only `Approval` bound to artifact version + content hash, decisions Approve/Request changes/Reject/Waive/Cancel, segregation of duties (author cannot self-approve or waive), waivers require reason + expiry, and a new version invalidates prior approval. Week 8 (work items, REQ-REQ-02/06) is implemented: the `WorkItem` hierarchy (Epic>Feature>Story>Task/Test Case) with `KEY-<n>` identifiers, acceptance criteria, priority/risk/status/owner, traceability to a baseline-or-derived, directed dependencies with circular-dependency rejection, and parent-cycle-safe reparenting. Week 9 (REQ-REQ-02/04) is implemented: version/hash-bound `RequirementAnalysis` runs with auditable provider/prompt/policy provenance, deterministic coverage and consistency findings (ambiguous, conflicting, duplicate, missing, untestable), blocking findings, schema-validated work-item proposals, idempotent proposal application, approval blocking until blocking findings are resolved or waived, explicit Heroku/RunPod fallback, bounded transient-provider retries, strict JSON-fence normalization, provider-output normalization for structured provenance/risk aliases, and configurable output-token bounds. The live pilot run created and approved baseline `aeab2014-bf03-4303-9afb-2ec6087fa684` (hash `729c6f5c339286e7f5e8377855a462c5004fbbefd3ad8b57e93dee7f9cf38548`), architecture `c27b8831-cbe5-4c4f-bf51-fe1a0768046f` (hash `af08fcb276b32cc670a1fa521f58ac8e5175bb2a4012d8c289103ea692a5cc7b`), and technical plan `56823201-cb83-4357-8fe5-c19e0ea71c3d` (hash `064dff7dda2bd6ff18215478ce8600de2a0da8028de17ca8b1f2e5a2c3acdcda`). Gate 2/3 control-plane approvals are recorded; further attestation is governed by organization/project gate policy.

### 5.3 Phase 3: Planning & Implementation - Weeks 14-21

| Week | Focus | Key tasks |
|------|-------|-----------|
| 14-15 | Technical plan | Repository-grounded, evidence-cited ordered plan: files, modules, DB changes, APIs, tests, risks, dependencies, rollback considerations, validation commands (REQ-PLN-01); typed environment-variable manifest (REQ-PLN-03); execution budget + permissions + escalation rules (REQ-PLN-04); feasibility checks - toolchains, permissions, migrations, test commands, inputs (REQ-PLN-05) |
| 16 | Plan approval gate | Enforce no production code modification before plan approval; blocked attempts fail with policy explanation + audit event (REQ-PLN-02) |
| 17 | Run control | Run console: plan, current step, tool calls, file diffs, model provider, limits, evidence; pause/cancel prevents new tool calls; checkpoint/resume with durable runs (REQ-COM-06, 16.2 `/agent-runs`) |
| 18 | Implementation | Bounded diff on dedicated branch/workspace; self review against requirements, architecture, conventions, security, quality; change-boundary enforcement - out-of-scope writes blocked/reverted + policy violation recorded (REQ-IMP-01/05) |
| 19 | Tests & self-healing | Test generation mapped to acceptance criteria; run suites in Docker; bounded corrections; rerun until pass or escalation at iteration/time/cost/scope/safety limits (REQ-IMP-02/03/04) |
| 20 | Verification pipeline | Dependency, secret, license, SAST, container-image scans; severity thresholds block acceptance; waivers approved + expiry (REQ-IMP-06); reproducible evidence - commit, image digest, lockfiles, env-manifest hash, commands, results, artifact hashes (REQ-IMP-07) |
| 21 | Change set review | Policy-selected review of staged change set; all mandatory suites pass; code review gate approved; cost/usage recording consolidated (REQ-COM-08) |

**Exit criteria / Gate 4:** Approved plan generates a reviewable change set with passing automated tests and policy-selected Developer/QA decisions.

**Status (implemented control plane + live worker run):** Weeks 14-21 planning and implementation controls are implemented: typed environment-variable manifests and feasibility sections, approved-plan-bound technical plans, generic version/hash approval, durable agent-run state with pause/cancel/checkpoints/events, plan-scoped tool/path permissions, reviewable change sets, self-review, hash-bound verification evidence with expiring waivers, and change-set approval. Migration `f7d3a1c5e8b2` adds the original planning schema; migration `c9e2f6a1d4b7` adds worker leases, attempts, and verification binding. `app.planning.worker.AgentRunWorker` claims queued runs with a database lease, resumes from checkpoints, invokes the strict Heroku/RunPod implementation contract, persists a draft change set without bypassing review, and refuses to persist after lease loss. Managed-inference endpoints are HTTPS-only, `scripts/validate_provider_config.py` provides a secret-safe preflight, and provider usage/cost fields are now preserved when returned by the gateway. A live Heroku `nova-2-lite` worker run completed with run `3088fe0b-e82c-4249-8d88-0bafa57a3e5b`, producing reviewable change set `02b9209b-45e4-448c-98db-5f545a851326` with 8 files. Inspection rejected that generated set because it invented an incompatible Flask structure and dependencies; no generated code was applied or approved. Gate 4 therefore remains open pending a valid reviewable set, bound tests/scans/reproducibility evidence, and policy-selected Developer/QA decisions.

### 5.4 Phase 4: UI/UX & Acceptance - Weeks 22-27

| Week | Focus | Key tasks |
|------|-------|-----------|
| 22-23 | Penpot integration | Design adapter: project/file reference, export/preview retrieval, node/page <-> work item association, comments/review links; unavailable write capabilities = documented human handoff, never simulated (REQ-UI-01/02, 16.4); mockup generation + review loop |
| 24-25 | UI implementation | UI code from approved mockups; isolated interactive preview (pinned, versioned) for review; story -> design -> implementation diff -> preview -> verification evidence links (REQ-UI-03/04); WCAG 2.2 AA baseline if core workflows (REQ-UI-05, NFR-10); hybrid web client build (Section 7) |
| 26 | HAT workspace | Isolated test deployment with scenario guidance + evidence links; per-criterion Pass/Fail/Blocked/N-A recording; preview protection - access control, expiration, environment labeling, non-production data rules (REQ-QA-01/04/06, NFR-09 support) |
| 27 | Defects | Defect logging + triage (severity, repro steps, expected/actual, attachments); regression-test-first automated remediation loop; human verification closes defect or reopens; flaky-test handling with bounded retry policy (REQ-QA-02/03/05) |

**Exit criteria / Gate 5:** A pilot feature passes mockup review, interactive preview, HAT, and defect remediation workflows. Owners: Product owner + Designer; QA engineer.

**Status (Phase 4 workbench and local pilot acceptance exercised):** The control-plane slice is implemented in migration `a2c4e6f8b0d1` and the `/design` blueprint: versioned mockup artifacts bound to approved architecture, Penpot file references with a read-only adapter and explicit human handoff, node/page-to-work-item links, anchored comments, mockup approval, commit-pinned authenticated previews with expiry, per-criterion acceptance sessions, and defects gated by regression evidence. A same-origin accessible operator workbench is served at `/workbench` for review, HAT result entry, and defect triage. An HTTPS preview deployment webhook adapter can provision a real non-production URL with strict response validation, and `scripts/validate_accessibility.py` produces baseline evidence. The local-only BotQ preview passed all six automated HAT criteria; the automated botq accessibility baseline also passed. Gate 5 can use automated acceptance for this pilot when the policy and evidence explicitly state that choice. Penpot remains intentionally out of scope for this local-only pilot unless separately required.

### 5.5 Phase 5: Release & Deployment - Weeks 28-31

| Week | Focus | Key tasks |
|------|-------|-----------|
| 28 | Readiness engine | Verify approval, test, defect, security, migration, configuration, artifact, rollback prerequisites; rule matrix Pass/Fail/Waived/N-A; block release on any mandatory failure (REQ-REL-01) |
| 29 | Packaging | Version tags, release notes, builds, SBOM (where configured), checksums, production Docker images from the approved commit with immutable identifiers (REQ-REL-02) |
| 30 | Deployment plan | Environment-specific plan: prechecks, migrations, backups, deployment steps, health checks, rollback triggers, recovery steps; execute only an approved plan version; publish diagnostics (REQ-REL-03); authorization only for release-allowed roles, dual control for production (REQ-REL-04) |
| 31 | Deploy, rollback, monitor | Policy-driven automatic rollback on health-threshold failure + manual rollback with DB compatibility; smoke checks + diagnostics over the observation period; release closes only when checks pass or authorized exception accepted (REQ-REL-05/06) |

**Exit criteria / Gate 6:** Approved pilot release deployed; post-deployment checks pass; release/security decisions recorded under the selected policy.

**Status (Phase 5 control plane implemented; local package exercise completed):** Release identity, readiness checks, immutable package
manifests, deployment-plan content validation, release/deployment approvals, production dual
control, deployment diagnostics, rollback records, and an HTTPS deployment webhook adapter are
implemented under `app.release`, migration `d4e7f9a2b6c1`, and the `/releases`,
`/deployment-plans`, and `/deployments` endpoints. The workflow is documented in
`docs/PHASE5_RELEASE_DEPLOYMENT.md`. The local BotQ image was built from the remediated pilot
working tree as digest `sha256:554644c469ce4d12c3c854b281a84e13f0ddd766db0a398c5faacdf0560894da`,
with package checksum `966546741c26e3f81ff2851758384219fb6c79f2adca5be6bb94e03470eb2c0c`; the
dependency audit found no known vulnerabilities. The current local adapter supports rollback only
through an explicit previous Compose definition; the earlier restart/base-image smoke result is not
treated as rollback evidence. The botq release API was not executed because the generated change set
is not approved. Gate 6 remains open pending a botq release record, approved deployment plan,
deployment diagnostics, and policy-selected release/security decisions.

### 5.6 Phase 6: Hardening - Weeks 32-35

| Week | Focus | Key tasks |
|------|-------|-----------|
| 32-33 | Security | OWASP-aligned controls, tenant-isolation tests, secret-leakage/egress/container-boundary/privilege checks; threat-model re-review; DR exercise - restore project, audit history, approvals, artifact references within RPO/RTO (NFR-05/14, REQ-INF-07); retention configuration (NFR-13) |
| 34 | Performance & reliability | API latency (95% reads < 500 ms, writes < 1 s non-streaming); independent web/worker scaling; load + concurrency tests; durability - restart recovery from safe checkpoints (NFR-02/03/04) |
| 35 | Operations | Structured logs, metrics, traces, correlation IDs; job-state metrics, model usage/cost, test outcomes, deployment health; alerting + runbooks per Appendix C; diagnostic bundles for failed jobs (NFR-09/15, REQ-COM-04); localization/retention go-live checks (NFR-12/13); production readiness review |

**Exit criteria / Gate 7:** Production readiness evidence accepted and Security/Operations decisions recorded against SRS 18.3 release gate rules.

**Status (Phase 6 hardening foundation exercised):** Request correlation, response
security headers, process-local request metrics, configurable rate-limit baseline,
redacted tenant-scoped diagnostic bundles, retention planning, worker job-state
metrics, security baseline checks, latency benchmark tooling, backup compatibility
drill tooling, custom UUID-safe backup serialization, and initial alert/runbook artifacts are implemented.
The full automated backend suite, security baseline, accessibility, formatting, and compilation checks
pass. See
`docs/PHASE6_HARDENING.md` and `docs/PHASE6_OPERATIONS.md`. The security baseline,
automated accessibility baseline, latency benchmark (30 requests, zero errors, p95
78.457 ms), backup checksum/compatibility drill, and disposable PostgreSQL restore
(186 rows restored in 8.513 seconds) passed. Local checkpoint recovery, Redis shared limiting,
retention, alert-rule validation, and local concurrency evidence are also recorded, including a
two-API warmed readiness run at concurrency 32 with p95 173.075 ms. Gate 7 remains open pending live
security evidence, production-scale load/performance evidence, production backup restore/RPO-RTO
validation, production alert integration, and production readiness decisions.

**E2E validation delivered:** A dedicated Dockerized HTTP suite now runs through
the nginx proxy against PostgreSQL, seeds isolated test identities, exercises the
API state machines across all major control-plane domains, and tears down its
Compose project and volumes. The deterministic run forces rules-based analysis
and an inert worker so it never calls Heroku, RunPod, Penpot, or deployment
webhooks. The latest run passed 10 tests; external provider success and real SSH
success remain opt-in validations documented in `docs/E2E_TESTING.md` and
`scripts/validate_git.ps1`.

---

## 6. Architecture (SRS 5.1 - 5.3)

### 6.1 Logical components

| Component | Responsibility | Proposed technology |
|-----------|----------------|---------------------|
| Web application | Dashboards, review screens, diff/log viewers, approvals | Flask rendered pages + focused web client (decision D01) |
| Control API | AuthN/AuthZ, workflow, artifact, approval APIs | Flask modular blueprints, app factory |
| Persistence + migration | Transactional project/workflow/audit/config data | PostgreSQL 15+, Flask-SQLAlchemy, Flask-Migrate/Alembic |
| Agent orchestrator | Planning, scoped subagents, tool selection, checkpoints, resumable context | LangChain Deep Agents |
| Job scheduler + workers | Async execution, durable jobs, retries | Queue per decision D03 |
| Execution sandbox | Checkout, builds, tests, previews, packaging | Docker via controlled runner (no docker socket), resource + network policy |
| Model gateway | Capability-based provider routing, quotas, retry, usage/cost | OpenAI Python SDK, Heroku Managed Inference and/or RunPod Serverless adapters |
| AWS adapter | Optional secrets, storage, logs, registry, compute, deployment | Boto3, least-privilege IAM |
| Design adapter | Mockups, exports, comments, traceability | Penpot integration API |
| Git adapter | Clone, fetch, branch, commit, tag, diff, push | Git over SSH, managed deploy keys |
| Notification service | Review requests, failures, approvals, deployment results | Email + optional webhooks |

### 6.2 Deployment topology (SRS 5.2)

- **Development/initial:** web app, worker service, reverse proxy, and PostgreSQL on one secured Linux VPS (Docker Compose).
- **Production:** database and execution workers separated from the web tier as workload/risk warrants.
- **Isolation:** agent containers never mount the Docker daemon socket; a controlled runner creates containers from allowlisted images with policy-validated resource settings.

### 6.3 Provider portability (SRS 5.3)

Workflows reference **capabilities** (reasoning, coding, vision, embedding, object storage, deployment) rather than hard-coded provider model IDs. Provider/model selection is versioned configuration, recorded on every run.

### 6.4 Interface rules (SRS 16.2 - 16.5)

- **API:** JSON, stable error codes, correlation IDs, pagination, idempotency keys for retryable mutations, optimistic concurrency for versioned edits, signed webhooks. Representative resources: `/projects`, `/projects/{id}/repositories`, `/requirement-baselines`, `/work-items`, `/artifacts`, `/agent-runs`, `/test-runs`, `/defects`, `/releases`, `/deployments`, `/audit-events`.
- **Git:** SSH + strict host-key verification; configurable branch naming; no force push unless policy permits; staged/committed diffs before push; confirmation for tags, protected-branch writes, release publishing.
- **Model/cloud:** official SDKs, explicit regions, least-privilege IAM, retries, usage capture, per-run budget bounds.

---

## 7. Technology Stack & Open Decisions (SRS 19.2 / 19.3)

**Fixed constraints (SRS 19.2):** Flask + Flask-SQLAlchemy + Flask-Migrate, PostgreSQL, LangChain Deep Agents, OpenAI Python SDK, Boto3, managed inference, Penpot integration, Docker on Linux, Git over SSH. The managed inference deployment may be RunPod Serverless, Heroku Managed Inference, or an approved combination/fallback.

**Planned stack (decided at detailed design):**

| Layer | Option(s) | Recommended starting point |
|-------|-----------|----------------------------|
| Frontend | Server-rendered Flask, SPA, hybrid | Hybrid: Flask API + focused web client if interactive diff/run streaming justifies it |
| Identity | Local accounts, OIDC, enterprise SSO | OIDC with local development fallback |
| Durable jobs | Celery, RQ, Dramatiq, workflow engine | Choose after proof of checkpoint, cancellation, recovery (D03) |
| Secrets | Encrypted DB, AWS Secrets Manager, Vault | External secret manager (production) + encrypted local substitute (dev) |
| Artifacts | VPS disk, object storage | S3-compatible object storage (production) |
| Git providers | Generic SSH, provider APIs | Generic SSH first; provider PR APIs on demand |
| Deployment target | Single VPS, Docker host, AWS, customer | Single controlled Docker host first; adapter-based extension |
| Approval policy | Single reviewer, dual control | Single (non-production); dual control (production + secret changes) |
| Retention | By artifact/environment | Define with Security + customer contract pre-production |
| Availability/RPO/RTO | Final SLA, RPO, RTO | Validate NFR targets during architecture (D10) |

**Decisions required before Phase 2 detailed design approval:**

| ID | Decision | Recommended | Owner | Deadline |
|----|----------|-------------|-------|----------|
| D01 | Frontend architecture | Hybrid | Tech lead | Gate 2 |
| D02 | Identity provider | OIDC + local fallback | Tech lead + Security | Gate 2 |
| D03 | Queue / durable jobs | After checkpoint proof | Tech lead | Gate 3 |
| D04 | Secret store | External manager (prod) | Security approver | Gate 2 |
| D05 | Artifact storage | S3-compatible object storage | Tech lead + DevOps | Gate 3 |
| D06 | Initial Git providers | Generic SSH first | Product owner | Gate 2 |
| D07 | Production deployment target | Controlled Docker host first | Release manager | Gate 5 |
| D08 | Approval policy | Dual control prod/secret | Security approver | Gate 2 |
| D09 | Data retention | With Security + contract | Security + Admin | Gate 6 |
| D10 | SLA / RPO / RTO | Validate NFR targets | Availability owner | Gate 3 |

### 7.1 Adopted decisions (D01-D06)

Recorded 2026-09-17 by the tech lead (owner of this build) as adopted for the pilot, with
rationale and the current implementation status. These are ADRs-in-summary; the architecture
package (Phase 2 weeks 11-13) will expand them into formal versioned ADR records (REQ-DES-03).

| ID | Decision | Adopted | Rationale | Implementation status |
|----|----------|---------|-----------|-----------------------|
| D01 | Frontend architecture | Hybrid | A server-rendered shell for auth/admin plus an SPA workbench for review/kanban; keeps the first slice simple while allowing rich interaction where it matters. | Backend API-first (JSON envelope) plus the accessible `/workbench` slice for Phase 4 review/HAT/defects; richer streaming/diff views remain future UI work (REQ-UI-*). |
| D02 | Identity provider | OIDC + local fallback | Enterprise SSO via OIDC for production; local password auth only for dev/tests so the stack runs offline. | Done: `auth/providers` (OIDC-ready + local), hashed bearer tokens; `OIDC_ENABLED`/`LOCAL_AUTH_ENABLED` gates. |
| D04 | Secret store | Local Fernet envelope now, external manager adapter in prod | Encrypted-at-rest baseline is testable offline; the adapter seam lets a Vault/KMS/SM provider drop in without touching call sites. | Done: `secrets/manager` with `fernet:` envelope + `SECRET_ENCRYPTION_KEY`, output masking, prompt-injection block; `secret_store` field reserves the external path. |
| D06 | Initial Git providers | Generic SSH first | Provider-neutral deploy-key + host-key-pinning flow works against any Git host (validated against a live SSH remote). GitHub/GitLab REST integrations layer on later. | Done: `git/` `GitCommandBackend` (SSH, strict host-key), validated end-to-end; provider APIs deferred. |
| D08 | Approval policy | Single reviewer non-prod; dual control for production/secret actions | Matches SRS 4.2 segregation-of-duties; keeps the pilot loop usable while reserving stricter policy for risky actions. | Done for the Phase 1-3 control plane: immutable approvals bound to version + hash, author cannot be sole approver, and architecture/plan/change-set gates reuse the same policy. |
| D03 | Queue / durable jobs | Defer until checkpoint proof | Phase 1 runs synchronous + a polling worker; introduce a durable queue only after the pilot proves throughput, avoiding premature infra. | Partially implemented (Gate 3): database-leased `AgentRunWorker` with checkpoint resume and polling is in place; Celery/RQ/Dramatiq selection remains open until pilot throughput evidence. |
| D05 | Artifact storage | Defer: S3-compatible object storage | Baseline attachments currently store references (name/url/hash); object storage lands with the planning phase. | Open (Gate 3): baseline `attachments` are by-reference only. |

D03 (queue), D05 (artifact storage), D07 (production deployment target), D09 (data retention),
and D10 (SLA/RPO/RTO) remain open or partially implemented and are scheduled for Gate 3, Gate 5,
and Gate 6 decisions as described below.

### 7.2 Current pending work and information required

The repository-side control plane is implemented through the Phase 6 foundation, but the remaining
gate work depends on a pilot environment, provider configuration, and named human owners. The
following items are still pending:

The principal pilot inputs are now supplied and recorded: Heroku managed inference with model
`nova-2-lite`, repository `git@github.com:cosq-network/botq-dev-pilot-1.git` on `main`, the recorded
GitHub host-key fingerprint, local-only preview, local Docker Compose deployment, 99.5% SLA, 24-hour
RPO, 8-hour RTO, the registration/login feature, and named reviewers. The pilot repository was
initialized at commit `31cbdb1`; this is application-scaffold evidence, not a completed botq gate.
See [`PILOT_STATUS.md`](PILOT_STATUS.md) for the complete matrix.

| Area | Pending evidence or decision | Information needed from the project owner |
|------|------------------------------|--------------------------------------------|
| Gate 2/3 pilot | Technical approval recorded; governance attestation as required | Baseline, architecture/ADR, and technical plan were created and approved in the local control plane; retain named human/review-board attestation if required by organizational policy |
| Managed inference | Live worker run completed; valid change-set acceptance pending | Heroku `nova-2-lite` worker run `3088fe0b...a3e5b` completed against the approved plan; generated change set `02b9209b...51326` was rejected in review and must be regenerated or corrected |
| Gate 4 verification | Exact-change-set verification and cost evidence pending | Local pilot tests/scans pass, but they are not yet bound to an accepted generated change-set hash; Heroku returned no usage/cost object in the completed run |
| Penpot / Gate 5 | Real design reference and designer review | Decide whether Penpot is required for this pilot; if yes, provide the Penpot instance/file and designer review |
| Preview / Gate 5 | Automated local acceptance passed; API evidence pending | Six HAT HTTP criteria and the automated accessibility baseline passed; record automated acceptance policy/evidence and any optional manual review; external preview is intentionally out of scope |
| Release / Gate 6 | Local package controls passed; botq release execution pending | Final image/package evidence is available and explicit previous-definition rollback is implemented; create/approve botq release/deployment records or configure an approved HTTPS deployment provider |
| Durable jobs (D03) | Final queue/scaling decision after pilot throughput evidence | Approve database-leased polling for the pilot or select Celery/RQ/Dramatiq/workflow service |
| Artifacts (D05) | Production artifact storage decision | Approve S3-compatible storage or explicitly accept controlled-disk limits for the pilot |
| Production target (D07) | Deployment topology and ownership | Controlled Docker host, AWS, customer environment, or another approved target |
| Retention (D09) | Contractual and operational retention policy | Audit/log/workspace/preview/artifact retention periods and approving Security/Admin owner |
| Responsibility assignments | Project-specific reviewers and approvers | APIs implemented for organization users/roles, project assignments, and optional assignment-enforced approvals; configure each pilot project and enable enforcement |
| Explicit gate control | Gate state and evidence lifecycle | Seven project gate APIs implemented for evidence, evaluation, decisions, close, reopen, and audit history |
| Availability (D10) | SLA, RPO/RTO and recovery evidence | Targets supplied: 99.5% / 24 hours / 8 hours; execute and approve recovery evidence |
| Gate 7 | Local baseline/recovery evidence passed; production readiness pending | Security baseline, p95 benchmark, backup/restore, metrics, alert definitions, checkpoint recovery, Redis sharing, retention, and local load passed; still require production topology/scale, live alert delivery, pilot assignment/policy configuration, and Security/Operations decision evidence |

#### How to supply the information

For local development, copy `backend/.env.example` to `backend/.env`. Put non-secret settings and
local-only credentials there; `.env` is ignored by Git and must not be committed. The relevant
variables include `REQUIREMENT_ANALYSIS_PROVIDER`, `AGENT_IMPLEMENTATION_PROVIDER`, the Heroku or
RunPod endpoint/model variables, `PENPOT_*`, `PREVIEW_DEPLOYMENT_*`, `DEPLOYMENT_*`, and the
retention/rate-limit settings. Run `scripts/validate_provider_config.py --json` after editing it.

For Docker Compose, the same runtime values are loaded from `backend/.env` and passed to the API
and worker services. For production, inject values through the deployment platform's environment
configuration or an external secret manager; do not commit a production `.env`, paste credentials
into chat, or place secrets in project records, prompts, logs, or API payloads. The application
expects the actual secret values at runtime, while the example files should contain only blanks or
safe placeholders.

Repository URLs, branches, fingerprints, reviewer names, retention decisions, SLA/RPO/RTO targets,
and approval decisions can be supplied in a reply or recorded in the relevant pilot/release
runbook. Credentials should be supplied only through the runtime secret-injection mechanism. Once
the non-secret choices and runtime configuration are available, the Implementation Team can run
the preflight scripts and produce the evidence packages; policy-selected API decisions and live-provider results
must still be recorded by their named owners.

### 7.3 Recommended next action sequence

The recommended next step is to execute a single controlled pilot rather than add more isolated
features. Use the following order so each gate produces the evidence required by the next gate:

1. **Use the confirmed pilot profile.** Heroku, the pilot repository/branch, local-only preview,
   local Docker Compose deployment, 99.5% SLA, 24-hour RPO, 8-hour RTO, feature scope, and named
   reviewers are recorded in `docs/PILOT_STATUS.md`.
2. **Prepare runtime configuration.** Copy `backend/.env.example` to the ignored `backend/.env`
   for local/Compose work, or inject the same variables through the production secret manager. Keep
   credentials out of Git and chat. Leave `AGENT_IMPLEMENTATION_PROVIDER=disabled` until the
   provider preflight passes.
3. **Run repository and configuration preflight.** Run provider, accessibility, security, and
   dependency checks; verify database readiness; and confirm the pilot Git host key. Resolve all
   failures before connecting live services.
4. **Close Gates 2/3 with the pilot.** Create the requirement baseline, analyze it, resolve or
   waive blocking findings, generate architecture/ADR/traceability records, and record the
   policy-selected Product Owner and Architecture Review decisions.
5. **Close Gate 4.** Enable the selected managed-inference provider, run the leased worker in the
   Linux Docker environment, inspect the draft change set, execute tests/scans, record hash-bound
   verification evidence, and record the policy-selected Developer/QA decisions.
6. **Close Gate 5.** Connect Penpot, review the mockup, provision a protected HTTPS preview, run
   HAT, resolve regression-gated defects, record automated accessibility evidence or policy-selected manual review, and record
   Product Owner/Designer/QA decisions.
7. **Close Gate 6.** Build the immutable image and SBOM, submit readiness evidence, approve the
   deployment plan under the selected release policy, deploy to the controlled target, perform health
   and rollback checks, and retain diagnostics.
8. **Close Gate 7.** Run the security review, production-scale performance test, PostgreSQL backup
   restore/RPO-RTO exercise, checkpoint restart test, alert integration, retention/localization
   checks, and the Security + Operations production-readiness review.

**Immediate recommendation:** create or verify `backend/.env` from the example and run
`scripts/validate_provider_config.py --json` plus the security/accessibility preflight. Then connect
the initialized repository through botq and execute Gate 2/3. Keep the external worker disabled until
the provider preflight and baseline/architecture approvals pass. Do not describe the pilot as
end-to-end complete until Gates 1–7 evidence is recorded.

For the complete operator sequence, evidence checklist, rollback procedure, and pilot exit boundary, use
[`docs/PILOT_EXECUTION_GUIDE.md`](PILOT_EXECUTION_GUIDE.md).

---

## 8. Non-Functional Baseline (SRS 17)

| ID | Category | Target |
|----|----------|--------|
| NFR-01 | Availability | 99.5% monthly (production control plane), excl. approved maintenance |
| NFR-02 | Performance | 95% of non-streaming API reads < 500 ms, writes < 1 s (excl. providers/long jobs) |
| NFR-03 | Scalability | Independent web/worker scaling; queue, active jobs, provider, DB, storage observable |
| NFR-04 | Durability | State + approvals survive restarts; resume from safe checkpoint or explicit recoverable state |
| NFR-05 | Security | OWASP-aligned controls, secure headers, CSRF, validation, rate limiting, dependency scanning, least privilege |
| NFR-06 | Privacy | Minimize provider data; data classification; provider allowlists + retention; no cross-tenant leakage |
| NFR-07 | Auditability | Privileged/lifecycle actions attributable + exportable; timestamps protected from update/delete |
| NFR-08 | Maintainability | Modular blueprints, app factory, typed services, migrations, automated tests, adapters |
| NFR-09 | Observability | Structured logs, metrics, traces, correlation IDs, usage/cost/health; no secret content |
| NFR-10 | Accessibility | WCAG 2.2 AA for core workflows |
| NFR-11 | Compatibility | Pinned stable versions; current + previous Chrome/Edge/Firefox/Safari |
| NFR-12 | Localization | Unicode + UTC storage; translation-ready architecture |
| NFR-13 | Retention | Configurable retention for logs, workspaces, previews, artifacts, audit |
| NFR-14 | Disaster recovery | RPO 24 h / RTO 8 h initial targets, tested before go-live |
| NFR-15 | Supportability | Safe diagnostic bundle: correlation ID, state history, env-manifest hash, logs, provider error class |

---

## 9. Verification, Traceability & Release Gates (SRS 18)

### 9.1 Verification methods

| Method | Applied to |
|--------|------------|
| Inspection | Document structure, approvals, audit events, configuration, artifacts, trace links |
| Demonstration | Interactive workflows, previews, pause/resume, review loops, deployment status |
| Automated test | API, authorization, data integrity, policies, adapters, isolation, migration, regression |
| Security test | Tenant isolation, secret leakage, injection, egress, container boundary, privilege |
| Recovery test | DB restore, job restart, failed deployment, rollback, provider outage |
| Performance test | API latency, job concurrency, queue behavior, logs, DB performance |

### 9.2 Release gate rules (SRS 18.3)

- No unresolved blocking requirement, architecture, UI, plan, code review, security, test, or defect item.
- All required approvals reference current artifact versions.
- Release commit = verified commit with a clean working tree.
- Mandatory tests and scans pass within allowed evidence age.
- Production configuration complete without exposing secret values.
- Deployment plan and rollback procedure approved and executable.
- Backup/recovery prerequisites satisfied before destructive migrations.

### 9.3 Traceability ownership (SRS 18.2)

| Requirement group | Primary evidence | Approval owner |
|-------------------|------------------|----------------|
| REQ-INF | Readiness reports, security tests, container policies, recovery evidence | Tech architect + Security approver |
| REQ-REQ | Requirement baseline, work item hierarchy, findings, approvals | Product owner |
| REQ-DES | Design package, ADRs, threat analysis, review history | Technical architect |
| REQ-UI | Penpot references, preview builds, accessibility evidence | Product owner + Designer |
| REQ-PLN | Repo analysis, technical plan, manifests, budget/permissions | Technical architect |
| REQ-IMP | Diff, self review, test results, scans, reproducibility record | Developer + QA engineer |
| REQ-QA | Acceptance record, defect history, regression test, human verification | QA engineer + Product owner |
| REQ-REL | Readiness report, release artifacts, approved plan, diagnostics | Release manager + Security approver |
| REQ-COM | Authorization, audit, search, notification, run control, cost tests | Organization administrator |

---

## 10. Dependencies & Prerequisites (provision before start)

| Dependency | Type | Provisioned by | Used in |
|------------|------|----------------|---------|
| Heroku Managed Inference app/endpoint(s) | External | Organization admin | Phase 3+ (optional if RunPod is selected) |
| OpenAI API access | External | Organization admin | Phase 3+ (if selected by provider policy) |
| RunPod Serverless endpoint(s) | External | Organization admin | Phase 3+ |
| Penpot instance + integration method | External | Designer | Phase 4 |
| AWS account (S3, optional Secrets Manager) | External | Org admin + DevOps | Phase 3-6 |
| OIDC identity provider | External | Tech lead + Security | Phase 1 |
| Linux VPS (dev) + production host, secure SSH | External | DevOps | Phase 1 |
| External secret store (production) | Internal | Security approver | Phase 2+ |
| Monitoring/logging baseline | Internal | DevOps | Phase 1 (base), Phase 6 (hardened) |
| Pilot repository (SSH access + legal rights) | Internal | Product owner | Phase 1-5 |

---

## 11. Risk Register & Failure Handling

### 11.1 Risks

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Model cost overruns | High | Medium | Per-project budgets, approval gates, capability-based cheaper defaults, usage capture (REQ-COM-08) |
| Agent prompt injection (tool output untrusted) | High | Medium | Untrusted-input handling, template prompts, output validation, no tool output as instructions (SRS Appendix B) |
| Security breach / secret leakage | Critical | Low | External secret store, masking, scans, tenant-isolation tests, least privilege |
| Git merge conflicts | Medium | High | Diff display, auto-refresh, human conflict resolution task (Appendix C) |
| Provider outage | Medium | Medium | Bounded retry with jitter, checkpoints, approved alternate provider, pause+escalate |
| Self-healing loops not converging | Medium | High | Hard iteration/time/cost/safety limits; escalate, never fabricate success |
| Deployment failure | Critical | Low | Readiness gates, pre-checks, dual control, rollback plan, health-based auto-rollback |
| Flaky/unstable tests | Medium | High | Bounded retry policy, flaky marking, triage or waiver (REQ-QA-05) |

### 11.2 Error handling requirements (SRS Appendix C)

| Condition | Required response |
|-----------|-------------------|
| Provider unavailable | Bounded retry with jitter, preserve checkpoint, approved alternate provider if policy allows, then pause |
| Git conflict | Stop auto-push, show conflict + affected files, human direction or approved resolution task |
| Test infrastructure failure | Classify separately, retry within policy, keep logs, no code changes without evidence |
| Migration failure | Stop deployment, capture DB state, follow approved rollback/recovery, release-manager review |
| Budget exceeded | Pause before next billable action; request revised budget authorization |
| Secret detected in output | Redact, restrict artifact access, emit security event, rotate if required, notify security approver |
| Worker interruption | Resume from safe checkpoint or mark recoverable; never report success from incomplete execution |
| Preview health failure | Do not open HAT; retain diagnostics; return to implementation or environment remediation |

---

## 12. Team, Roles & Governance

### 12.1 Team (FTE estimates)

| Role (SRS role mapping) | FTE |
|-------------------------|-----|
| Product owner (Product owner) | 0.5 |
| Tech lead (Architect) | 0.8 |
| Backend developer (Developer) | 1.5 |
| Frontend developer (Developer) | 1.0 |
| AI/ML engineer (Developer/AI agent enablement) | 1.0 |
| Security engineer (Security approver) | 0.8 |
| DevOps engineer (Infra/Release) | 1.0 |
| QA engineer (QA engineer) | 0.8 |
| Release manager (Release manager) | 0.5 |
| SRE (Auditor/Ops support) | 0.5 |
| Designer (Designer) | 0.5 |

**Governance rules:** all team members hold explicit SRS roles; **SoD** - a user may hold multiple roles but never be the sole approver of their own release plan or deployment change; automation satisfies approval only when an explicit policy selects a dedicated automation principal.

### 12.2 Approval gates

| Gate | Decision authority | Criteria |
|------|--------------------|----------|
| G1 Foundation | Infra review board | Secure project, repo cloned, diagnostic run passed |
| G2 Requirements | Product owner | Baseline approved, blocking findings = 0 |
| G3 Architecture | Architecture review board | Architecture + ADRs signed off, decisions D01-D10 resolved |
| G4 Implementation | Developer + QA | Approved plan, reviewable change set, tests pass |
| G5 Acceptance | Product owner + QA | Mockup, preview, HAT, remediation passed |
| G6 Release | Release manager + Security | Readiness matrix pass, artifacts immutable |
| G7 Production | Security + Operations | SRS 18.3 gate rules satisfied, readiness review approved |

---

## 13. Assumptions & Constraints (SRS 19.1 / 19.2)

**Assumptions:** platform serves software engineering teams (not public users); one primary Git repository per project in first release; customer supplies legal rights to connected repos/data; human reviewers own product/security/compliance/production decisions; providers may differ by project/data class; Penpot capabilities depend on deployed version.

**Constraints (binding):** Flask + Flask-SQLAlchemy + Flask-Migrate; PostgreSQL; LangChain Deep Agents; OpenAI SDK, Boto3, managed inference through RunPod Serverless and/or Heroku Managed Inference, Penpot; Docker on Linux; Git over SSH keys.

---

## Appendix A: Requirement-to-Phase Index

| Group | Requirements | Phase(s) |
|-------|--------------|----------|
| Infrastructure | REQ-INF-01..07 | 1 (base), 6 (DR/validation) |
| Requirements/work items | REQ-REQ-01..06 | 2 |
| Design/architecture | REQ-DES-01..05 | 2 |
| UI/UX | REQ-UI-01..05 | 4 |
| Planning/env | REQ-PLN-01..05 | 3 |
| Implementation/verification | REQ-IMP-01..07 | 3 |
| QA/defects | REQ-QA-01..06 | 4 (foundation 3) |
| Release/deployment | REQ-REL-01..06 | 5 |
| Cross-cutting | REQ-COM-01..08 | 1-6 |
| Non-functional | NFR-01..15 | 1 (base), 6 (validation) |

## Appendix B: Agent Control Policy (SRS Appendix B)

- Every run declares objective, inputs, permitted tools, writable paths, environment, model config, budget, time/iteration limits, approver.
- High-impact actions (production deploy, destructive migration, secret rotation, tag publication, protected-branch write, broadened network) require interrupt + explicit human confirmation.
- Tool output is untrusted input; agents resist prompt injection from repo files, logs, issues, web content, artifacts.
- Agents never weaken tests, delete validation, change acceptance criteria, or suppress failures for a passing result unless an approved change requires it.
- Agents preserve and display material uncertainty; failure to diagnose within bounds escalates rather than fabricating success.
- Subagents receive permissions equal to or narrower than the parent run and cannot expand scope independently.

## Appendix C: Document Control

| Version | Date | Change |
|---------|------|--------|
| 1.0 | Sept 2026 | Initial roadmap |
| 1.1 | Sept 2026 | Aligned to SRS v1.0: requirement IDs, success measures, lifecycle/gates, logical components, NFR baseline, decisions, verification, error handling |
| 1.2 | Sept 2026 | Recorded Phase 2/3 control-plane delivery, Phase 4 design/preview/acceptance start, managed inference portability, and operational gate blockers |
| 1.3 | Sept 2026 | Added leased Phase 3 agent worker, strict Heroku/RunPod implementation contract, plan-scoped run permissions, and hash-bound verification evidence |
| 1.4 | Sept 2026 | Added the accessible Phase 4 operator workbench for mockup review, preview launch, HAT evidence, and defect triage |
| 1.5 | Sept 2026 | Added the HTTPS preview deployment adapter contract and automated workbench accessibility evidence |
| 1.6 | Sept 2026 | Added secret-safe provider preflight, HTTPS-only inference enforcement, worker lease-loss protection, and the Phase 2–4 pilot runbook |
| 1.7 | Sept 2026 | Started Phase 5 with release readiness, package manifests, deployment plans, dual control, diagnostics, rollback records, and the HTTPS deployment adapter |
| 1.8 | Sept 2026 | Started Phase 6 hardening with request observability, security headers, rate-limit baseline, safe diagnostic bundles, and retention planning |
| 1.9 | Sept 2026 | Added Phase 6 security baseline, dependency scan, latency benchmark, recovery compatibility drill, worker metrics, alert rules, and operations runbook |
| 2.0 | Sept 2026 | Added the current pending-work matrix, project-owner information checklist, and safe local/production configuration handoff guidance |
| 2.1 | Sept 2026 | Added the recommended pilot-first action sequence and immediate next-step guidance for Gates 2–7 |
| 2.2 | Sept 2026 | Added the end-to-end pilot execution guide and linked it from the roadmap and README |
| 2.3 | Sept 2026 | Recorded the initialized BotQ Pilot repository, confirmed pilot decisions, and added the live completion/status matrix |
| 2.4 | Sept 2026 | Recorded the successful Heroku requirement-analysis run, submitted pilot baseline, GitHub deploy-key authorization blocker, and bounded managed-inference output handling |
| 2.5 | Sept 2026 | Closed Gate 1 after GitHub deploy-key authorization, botq connection testing, and synchronized main-branch evidence |
| 2.6 | Sept 2026 | Recorded full automated-suite validation, deterministic test-provider isolation, and the custom UUID-safe backup serializer fix |
| 2.7 | Sept 2026 | Added the Dockerized HTTP API E2E suite, Compose isolation/runner, CI job, endpoint workflow coverage, and fixed numeric release approval bindings |
| 2.8 | Sept 2026 | Added API-only gate policy/automation documentation, evidence/decision endpoint guidance, and updated pilot evidence requirements |

*Document maintained by the Implementation Team* - *Pending SRS v1.0 stakeholder approval*
