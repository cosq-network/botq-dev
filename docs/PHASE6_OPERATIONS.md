# Phase 6 — Operations and recovery runbook

This is the repository-side runbook baseline. Production owners must connect
the alert rules in `ops/alerts.yml` to the selected metrics collector and
record the resulting incident and recovery evidence before Gate 7.

For the current BotQ Pilot, the selected target is local Docker Compose with a
99.5% availability target, 24-hour RPO, and 8-hour RTO. Local recovery and
readiness exercises have supporting evidence; production-scale load, live alert
delivery, and final Gate 7 readiness decisions must be recorded through the gate
API before production readiness is claimed.

## Readiness failure

1. Check `/health/live` and `/health/ready` with the correlation ID recorded
   by the probe or reverse proxy.
2. Check database connectivity and recent API logs without exporting request
   bodies, authorization headers, prompts, or secret values.
3. If the database is unavailable, stop release/deployment activity and follow
   the approved database recovery procedure.

## Elevated HTTP errors

Inspect `/health/metrics`, group errors by route/status, and correlate with
deployment IDs and provider error classes. Roll back only through the approved
Phase 5 deployment plan and retain the provider diagnostics.

## Agent-run failures

Use the tenant-scoped diagnostic bundle, inspect the run state/checkpoint and
provider error class, then verify lease ownership before retrying. Do not
approve or apply a generated change set as part of incident response.

## Latency budget

Run `python scripts/benchmark_api.py --url https://<host> --json` from an
approved network location. Record endpoint, iteration count, p95, error count,
deployment version, and database/provider conditions. The script measures a
live endpoint; it does not prove multi-worker or production-scale capacity.

## Backup and recovery drill

Verify an archive and run the non-destructive compatibility drill:

```text
python scripts/validate_recovery.py backups/<archive>.tar.gz --json
```

The drill verifies the checksum, required control-plane tables, and restore
mapping in an isolated in-memory database. A real RPO/RTO exercise must use an
isolated PostgreSQL target and be approved by Operations before any destructive
restore.

## Gate 7 API evidence

Submit operations evidence to Gate 7 with explicit source, command, timestamp,
result, and content hash. For the API-only pilot, the automation principal may
record the operations-readiness decision only after mandatory checks are passed,
waived with reason/expiry, or marked not applicable by policy. Missing checks
remain blocked in `/api/v1/projects/{project_id}/gates/summary`.
