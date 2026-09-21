# Phase 6 — Hardening foundation

This document records the repository-side Phase 6 work and the local pilot exercises run in September
2026. The pilot has selected a 99.5% availability target, 24-hour RPO, and 8-hour RTO. The local
security, latency, backup compatibility, and disposable PostgreSQL restore exercises passed, but this
document does not substitute for production-scale load, live alert delivery, or the production
readiness evidence required by Gate 7.

## Implemented in this slice

- Request correlation is returned as `X-Correlation-ID` and included in the
  request-completion log event.
- Process-local request counters and bounded duration summaries are exposed at
  `GET /health/metrics` and Prometheus exposition is available at
  `GET /health/metrics/prometheus`. The values contain no request payloads,
  headers, tokens, prompts, or tenant identifiers.
- Baseline security headers are applied to every response. HSTS is enabled
  only when `ENVIRONMENT=production`.
- Protected API mutations use bearer tokens rather than ambient cookies; the
  OIDC session is limited to the nonce/organization handshake and uses secure,
  HTTP-only, SameSite=Lax cookie settings in production.
- A configurable fixed-window rate-limit baseline is available with
  `RATE_LIMIT_ENABLED` and `RATE_LIMIT_PER_MINUTE`. Production deployments
  still need a shared edge limiter for multiple web processes.
- Auditors and administrators can request a tenant-scoped, redacted diagnostic
  bundle at `GET /api/v1/diagnostics/bundle`.
- Configurable retention periods are reported by
  `GET /api/v1/diagnostics/retention-plan`. This is intentionally plan-only;
  audit-chain deletion needs archival and re-sealing authority before it can
  be automated.
- Repository-side security, latency, and backup-compatibility evidence tools
  are available as `scripts/validate_security_baseline.py`,
  `scripts/benchmark_api.py`, and `scripts/validate_recovery.py`.
- Worker execution now contributes agent-run status and duration metrics.
- Initial alert definitions and response procedures are documented in
  `ops/alerts.yml` and `docs/PHASE6_OPERATIONS.md`.
- Prometheus scrape and Grafana dashboard templates are in `ops/`; run
  `python scripts/test_alert_rules.py` to validate the checked-in alert baseline.
- Rate limiting supports `RATE_LIMIT_BACKEND=memory` or opt-in Redis (`REDIS_URL`).
- Retention supports audited dry runs and deletion of expired agent events/checkpoints; audit events
  remain preserved pending archival/re-sealing authority.
- Configuration handoff requirements and the safe `.env`/production-secret distinction are recorded
  in `docs/IMPLEMENTATION_ROADMAP.md` section 7.2 and `backend/.env.example`.

## Recorded local pilot evidence

- Security-header and template baseline: passed.
- Automated botq accessibility baseline: passed.
- Readiness latency benchmark: 30 requests, zero errors, p95 `78.457 ms` against the `500 ms` target.
- Backup checksum/compatibility drill: passed; all required tables present.
- Disposable PostgreSQL restore: 186 rows restored in `8.513 s`.
- Metrics endpoints returned populated request counters and Prometheus exposition; alert rules are
  present in `ops/alerts.yml`.
- Linux CI-equivalent suite passed: 156 backend tests, Ruff, Bandit, pip-audit, and Docker build.
- Dockerized API E2E passed: 10 tests.
- Checkpoint recovery passed after simulated lease expiry/interruption and worker reclaim.
- Local Compose health load passed: 300 requests at concurrency 32, zero errors, p95 `157.863 ms`.
- Two-API local Compose topology passed a warmed readiness load of 2,000 requests at concurrency
  32 with zero errors and p95 `173.075 ms`; liveness at concurrency 64 passed with p95 `194.854 ms`.
  An initial cold 64-concurrency readiness run measured p95 `642.059 ms`, so the warm-up condition is
  retained in the evidence rather than hidden.
- Redis shared rate limiting passed across two independent Flask app instances: three successes then
  HTTP 429.
- Retention dry-run preserved all records; controlled execution removed one synthetic run event and
  checkpoint while preserving and appending audit events.
- Local Compose deployment adapter implementation supports deploy, health check, and explicit
  previous-definition rollback; a restart-only exercise is not treated as rollback evidence.
- Release evidence contains dependency SBOM/checksums and immutable local image ID
  `sha256:d4f86bf3...240daf`.
- Explicit gate-control API coverage passed for policy configuration, automation principals,
  evidence submission, API automation decisions, closure blocking, reopen behavior, and summary.

## Evidence still required for Gate 7

- OWASP/dependency scan results beyond the repository baseline, tenant-isolation/egress/container-boundary
  review, and threat-model re-review.
- PostgreSQL backup restore exercise proving the 24-hour RPO and 8-hour RTO,
  including approvals, audit history, and artifact references.
- Production-scale load/concurrency results proving the NFR-02 latency targets and a real worker
  restart recovery test proving checkpoint durability.
- Production metrics export, alert rules, on-call runbooks, and a review of
  provider usage/cost and deployment-health signals.
- Localization/retention go-live checks and Security + Operations decision records, or API automation
  decisions when project policy selects `api_automation`.
