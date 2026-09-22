# Frontend route coverage

The SPA is served from the same origin as the API.  Project-scoped state is
selected with the `project` URL parameter and all server state is keyed by
organization/project context in TanStack Query.

| Backend domain | Frontend destination |
| --- | --- |
| Authentication/session | `/login`, `/auth/callback` |
| Organization/users/roles/policy | `/organization/*`, `/settings/*` |
| Projects/responsibilities | `/projects`, `/projects/:projectId` |
| Requirements/findings | `/requirements` |
| Work items/dependencies | `/work-items` |
| Traceability links/search | `/traceability` |
| Architecture/ADRs/comments | `/architecture`, `/architecture/:architectureId` |
| Plans/agent runs/checkpoints | `/planning` |
| Change sets/verifications | `/change-sets` |
| Design/mockups/previews/defects | `/design`, `/preview-control` |
| Human acceptance | `/acceptance` |
| Approvals/gates/evidence | `/approvals`, `/gates` |
| Releases/deployment plans/deployments/rollback | `/releases`, `/deployment-control` |
| Git repositories | `/repository` |
| Secrets | `/secrets` |
| Sandbox/probes | `/sandbox` |
| Audit/diagnostics/retention/health/metrics | `/operations`, `/operations/control` |

The backend remains authoritative for scopes, lifecycle transitions, approval
requirements, confirmation, tenant isolation, and all destructive operations.

## Implementation and verification status

The SPA uses generated OpenAPI TypeScript contracts and generated Orval TanStack Query hooks with
a centralized same-origin client for credentials, CSRF, correlation IDs, error normalization, and
session expiry. It is built into a production-like Nginx image with hashed assets and SPA fallback.

Local verification currently includes four Vitest unit/accessibility tests, strict TypeScript
checking, ESLint, dependency audit, production build, 27 Playwright browser tests, and axe checks
on the major route surfaces. The Dockerized backend workflow also validates the API and database
boundary. These checks establish route and shell coverage; real provider mutations and production
deployment/operations evidence remain environment-specific.
