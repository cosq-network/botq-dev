import type { paths as OpenApiPaths } from './api/generated'
import { generatedClient } from './api/generated-client'

export type GeneratedApiPaths = OpenApiPaths
export type ApiEnvelope<T> = { ok: boolean; data?: T; message?: string; correlation_id: string; error?: { code: string; message: string; details?: unknown } }
export type User = { id: string; email: string; display_name: string; roles: string[] }
export type Session = { user: User; scopes: string[]; organization: { id: string; name: string; slug: string } }
export type Project = { id: string; name: string; key: string; description?: string; lifecycle_state: string; default_branch: string; archived: boolean; created_at: string; updated_at: string; repository?: unknown }
export type Baseline = { id: string; project_id: string; title: string; status: string; current_version: number; created_by: string; created_at: string; updated_at: string; version_count: number; content?: Record<string, unknown>; content_hash?: string }
export type Finding = { id: string; analysis_id: string; category: string; severity: string; blocking: boolean; status: string; title: string; description: string; evidence: unknown; resolution?: string }
export type Analysis = { id: string; project_id: string; baseline_id: string; baseline_version: number; baseline_hash: string; status: string; summary: Record<string, unknown>; proposed_work_items: unknown[]; findings?: Finding[] }
export type WorkItem = { id: string; code: string; project_id: string; kind: string; title: string; description?: string; status: string; priority: string; risk: string; estimate?: number; source_baseline_id?: string; parent_id?: string }
export type Gate = { id: string; project_id: string; number: number; name: string; status: string; required_evidence: string[]; blocking_checks: string[]; missing_decisions: string[]; decisions?: { responsibility_type: string; decision: string; comment?: string }[]; evaluated_at?: string }
export type Artifact = { id: string; project_id: string; title: string; status: string; current_version: number; content_hash?: string; content?: Record<string, unknown>; source_baseline_id?: string; source_artifact_id?: string }
export type AgentRun = { id: string; project_id: string; plan_artifact_id: string; objective: string; status: string; plan_version: number; budget: Record<string, unknown>; allowed_tools: string[]; writable_paths: string[]; current_step?: string; pause_reason?: string }
export type Mockup = Artifact & { design_reference?: { file_id: string; file_url?: string; preview_url?: string }; comments?: unknown[] }
export type Preview = { id: string; project_id: string; mockup_artifact_id: string; status: string; url?: string; environment: string; expires_at: string; access_policy: Record<string, unknown> }
export type Defect = { id: string; project_id: string; title: string; severity: string; status: string; expected: string; actual: string }
export type Release = { id: string; project_id: string; version: string; commit_sha: string; status: string; readiness?: { passed?: boolean; blocking?: string[] }; package?: Record<string, unknown> }
export type DeploymentPlan = { id: string; release_id: string; environment: string; status: string; content_hash?: string }
export type Deployment = { id: string; release_id: string; environment: string; status: string; provider: string; provider_deployment_id?: string }
export type ChangeSet = { id: string; project_id: string; run_id: string; branch: string; base_commit: string; status: string; diff_hash?: string; self_review?: Record<string, unknown>; files: { path: string; action: string; content_hash: string }[]; verifications: Verification[] }
export type Verification = { id: string; kind: string; command: string; status: string; result: Record<string, unknown>; change_set_hash: string }
export type AcceptanceSession = { id: string; project_id: string; preview_id: string; status: string; criteria: { key: string; label?: string }[]; results?: { criterion_key: string; outcome: string; notes?: string }[] }
export type Repository = { id: string; ssh_url: string; host: string; host_fingerprint_verified: boolean; scope: string; default_branch: string; status: string; deploy_key_public?: string; last_sync_at?: string; last_error?: string }
export type Secret = { id: string; name: string; purpose?: string; secret_store: string; status: string; key_ref?: string; last_accessed_at?: string; last_rotated_at?: string }
export type OrganizationUser = { id: string; email: string; display_name: string; roles: string[]; user_type?: string; is_active: boolean; last_login_at?: string }
export type OrganizationRole = { name: string; scopes: string[]; is_system: boolean }
export type GatePolicy = { approval_mode: string; require_gate_decisions: boolean; require_project_responsibility_assignment: boolean; allow_waivers: boolean; require_previous_gate_closed: boolean; auto_sync_evidence: boolean; version: string }
export type ResponsibilityAssignment = { id: string; project_id: string; user_id: string; user_email?: string; user_display_name?: string; responsibility_type: string; is_primary: boolean; segregation_group?: string; effective_from?: string; effective_until?: string }
export type TraceLink = { id: string; project_id: string; source_type: string; source_id: string; target_type: string; target_id: string; relation: string; created_by: string; created_at: string }
export type ArchitectureComment = { id: string; artifact_id: string; version: number; anchor: Record<string, unknown>; body: string; status: string; created_by: string; resolved_by?: string; created_at: string }
export type Adr = { id: string; artifact_id: string; version: number; key: string; title: string; context: string; decision: string; consequences: string; status: string; created_by: string; created_at: string }

function csrfToken() {
  return document.cookie.split('; ').find((part) => part.startsWith('csrf_token='))?.split('=').slice(1).join('=')
}

export class ApiError extends Error {
  status: number; code: string; correlationId?: string
  constructor(message: string, status: number, code = 'api_error', correlationId?: string) { super(message); this.status = status; this.code = code; this.correlationId = correlationId }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method ?? 'GET').toUpperCase()
  const headers = new Headers(init.headers)
  headers.set('Accept', 'application/json')
  if (init.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
    const token = csrfToken()
    if (token) headers.set('X-CSRF-Token', decodeURIComponent(token))
  }
  const response = await fetch(path, { ...init, headers, credentials: 'include' })
  const body = await response.json().catch(() => ({})) as ApiEnvelope<T>
  if (!response.ok || body.ok === false) {
    throw new ApiError(body.error?.message ?? 'The request could not be completed.', response.status, body.error?.code, body.correlation_id)
  }
  return body.data as T
}

export const getSession = () => api<Session>('/api/v1/auth/me')
export const getProviders = () => api<{ name: string; login_url: string }[]>('/api/v1/auth/providers')
export const login = (payload: { email: string; password: string; organization?: string }) => api<Session>('/api/v1/auth/login', { method: 'POST', headers: { 'X-Auth-Mode': 'cookie' }, body: JSON.stringify(payload) })
export const logout = () => api('/api/v1/auth/logout', { method: 'POST' })
export const list = (path: string) => api<unknown[]>(path)
export const projects = () => api<Project[]>('/api/v1/projects')
export const project = (id: string) => api<Project>(`/api/v1/projects/${id}`)
export const organization = () => api<{ id: string; name: string; slug: string; settings: Record<string, unknown> }>('/api/v1/organizations/me')
export const organizationUsers = () => api<OrganizationUser[]>('/api/v1/organizations/me/users')
export const organizationRoles = () => api<OrganizationRole[]>('/api/v1/organizations/me/roles')
export const updateOrganizationSettings = (payload: { enforce_project_responsibilities: boolean }) => api<{ id: string; settings: Record<string, unknown> }>('/api/v1/organizations/me/settings', { method: 'PATCH', body: JSON.stringify(payload) })
export const gatePolicy = () => api<GatePolicy>('/api/v1/organizations/me/gate-policy')
export const updateGatePolicy = (payload: Partial<GatePolicy>) => api<GatePolicy>('/api/v1/organizations/me/gate-policy', { method: 'PATCH', body: JSON.stringify(payload) })
export const createOrganizationUser = (payload: { email: string; display_name: string; password?: string; user_type?: string; roles?: string[] }) => api<OrganizationUser>('/api/v1/organizations/me/users', { method: 'POST', body: JSON.stringify(payload) })
export const updateOrganizationUser = (id: string, payload: Record<string, unknown>) => api<OrganizationUser>(`/api/v1/organizations/me/users/${id}`, { method: 'PATCH', body: JSON.stringify(payload) })
export const replaceOrganizationUserRoles = (id: string, roles: string[]) => api<OrganizationUser>(`/api/v1/organizations/me/users/${id}/roles`, { method: 'PUT', body: JSON.stringify({ roles }) })
export const createProject = (payload: { name: string; key: string; description?: string; default_branch?: string }) => api<Project>('/api/v1/projects', { method: 'POST', body: JSON.stringify(payload) })
export const baselines = (projectId: string) => api<Baseline[]>(`/api/v1/requirements/baselines?project_id=${encodeURIComponent(projectId)}`)
export const baseline = (id: string) => api<Baseline>(`/api/v1/requirements/baselines/${id}`)
export const baselineVersions = (id: string) => api<unknown[]>(`/api/v1/requirements/baselines/${id}/versions`)
export const baselineVersion = (id: string, version: number) => api<unknown>(`/api/v1/requirements/baselines/${id}/versions/${version}`)
export const baselineDiff = (id: string, from: number, to: number) => api<unknown>(`/api/v1/requirements/baselines/${id}/versions/${from}/diff?to=${to}`)
export const createBaseline = (payload: { project_id: string; title: string; content: Record<string, unknown> }) => api<Baseline>('/api/v1/requirements/baselines', { method: 'POST', body: JSON.stringify(payload) })
export const baselineAction = (id: string, action: 'submit' | 'analyze' | 'approve' | 'reject' | 'request-changes' | 'cancel') => api<Baseline>(`/api/v1/requirements/baselines/${id}/${action}`, { method: 'POST', body: JSON.stringify({}) })
export const analyses = (baselineId: string) => api<Analysis[]>(`/api/v1/requirements/baselines/${baselineId}/analyses`)
export const analysis = (analysisId: string) => api<Analysis>(`/api/v1/requirements/analyses/${analysisId}`)
export const resolveFinding = (analysisId: string, findingId: string, status: 'resolved' | 'waived', reason: string) => api<Finding>(`/api/v1/requirements/analyses/${analysisId}/findings/${findingId}/resolve`, { method: 'POST', body: JSON.stringify({ status, reason }) })
export const applyAnalysisWorkItems = (analysisId: string) => api<WorkItem[]>(`/api/v1/requirements/analyses/${analysisId}/work-items`, { method: 'POST', body: JSON.stringify({}) })
export const workItems = (projectId: string) => api<WorkItem[]>(`/api/v1/work-items?project_id=${encodeURIComponent(projectId)}`)
export const workItem = (id: string) => api<WorkItem>(`/api/v1/work-items/${id}`)
export const workItemDependencies = (id: string) => api<WorkItem[]>(`/api/v1/work-items/${id}/dependencies`)
export const workItemTree = (projectId: string) => api<unknown[]>(`/api/v1/work-items/tree?project_id=${encodeURIComponent(projectId)}`)
export const responsibilities = (projectId: string) => api<ResponsibilityAssignment[]>(`/api/v1/projects/${projectId}/responsibility-assignments`)
export const createResponsibility = (projectId: string, payload: Record<string, unknown>) => api<ResponsibilityAssignment>(`/api/v1/projects/${projectId}/responsibility-assignments`, { method: 'POST', body: JSON.stringify(payload) })
export const updateResponsibility = (projectId: string, id: string, payload: Record<string, unknown>) => api<ResponsibilityAssignment>(`/api/v1/projects/${projectId}/responsibility-assignments/${id}`, { method: 'PATCH', body: JSON.stringify(payload) })
export const createWorkItem = (payload: { project_id: string; kind: string; title: string; description?: string; priority?: string; risk?: string; source_baseline_id?: string }) => api<WorkItem>('/api/v1/work-items', { method: 'POST', body: JSON.stringify(payload) })
export const updateWorkItem = (id: string, payload: Record<string, unknown>) => api<WorkItem>(`/api/v1/work-items/${id}`, { method: 'PATCH', body: JSON.stringify(payload) })
export const gates = (projectId: string) => api<Gate[]>(`/api/v1/gates/${projectId}/gates`)
export const gateAction = (projectId: string, number: number, action: 'sync' | 'evaluate') => api<Gate>(`/api/v1/gates/${projectId}/gates/${number}/${action}`, { method: 'POST', body: JSON.stringify({}) })
export const gateDecision = (projectId: string, number: number, payload: { responsibility_type: string; decision: string; comment?: string }) => api<Gate>(`/api/v1/gates/${projectId}/gates/${number}/decisions`, { method: 'POST', body: JSON.stringify(payload) })
export const closeGate = (projectId: string, number: number) => api<Gate>(`/api/v1/gates/${projectId}/gates/${number}/close`, { method: 'POST', body: JSON.stringify({}) })
export const reopenGate = (projectId: string, number: number, reason: string) => api<Gate>(`/api/v1/gates/${projectId}/gates/${number}/reopen`, { method: 'POST', body: JSON.stringify({ reason }) })
export const gateHistory = (projectId: string, number: number) => api<unknown[]>(`/api/v1/gates/${projectId}/gates/${number}/history`)
export const approvals = (projectId?: string) => api<unknown[]>(`/api/v1/approvals${projectId ? `?project_id=${encodeURIComponent(projectId)}` : ''}`)
export const architecturePackages = (projectId: string) => api<Artifact[]>(`/api/v1/architecture/packages?project_id=${encodeURIComponent(projectId)}`)
export const architecturePackage = (id: string) => api<Artifact>(`/api/v1/architecture/packages/${id}`)
export const createAdr = (id: string, payload: { key: string; title: string; context: string; decision: string; consequences: string }) => api<Adr>(`/api/v1/architecture/packages/${id}/adrs`, { method: 'POST', body: JSON.stringify(payload) })
export const architectureComments = (id: string) => api<ArchitectureComment[]>(`/api/v1/architecture/packages/${id}/comments`)
export const addArchitectureComment = (id: string, payload: { body: string; anchor?: Record<string, unknown>; version?: number }) => api<ArchitectureComment>(`/api/v1/architecture/packages/${id}/comments`, { method: 'POST', body: JSON.stringify(payload) })
export const resolveArchitectureComment = (id: string) => api<ArchitectureComment>(`/api/v1/architecture/comments/${id}/resolve`, { method: 'POST', body: JSON.stringify({}) })
export const createArchitecture = (payload: { project_id: string; source_baseline_id: string; title: string; content: Record<string, unknown> }) => api<Artifact>('/api/v1/architecture/packages', { method: 'POST', body: JSON.stringify(payload) })
export const architectureAction = (id: string, action: 'submit' | 'approve' | 'request-changes' | 'reject') => api<Artifact>(`/api/v1/architecture/packages/${id}/${action}`, { method: 'POST', body: JSON.stringify({}) })
export const plans = (projectId: string) => api<Artifact[]>(`/api/v1/plans?project_id=${encodeURIComponent(projectId)}`)
export const plan = (id: string) => api<Artifact>(`/api/v1/plans/${id}`)
export const createPlan = (payload: { project_id: string; source_architecture_id: string; title: string; content: Record<string, unknown> }) => api<Artifact>('/api/v1/plans', { method: 'POST', body: JSON.stringify(payload) })
export const planAction = (id: string, action: 'submit' | 'approve' | 'request-changes' | 'reject') => api<Artifact>(`/api/v1/plans/${id}/${action}`, { method: 'POST', body: JSON.stringify({}) })
export const agentRuns = (projectId: string) => api<AgentRun[]>(`/api/v1/agent-runs?project_id=${encodeURIComponent(projectId)}`)
export const agentRun = (id: string) => api<AgentRun>(`/api/v1/agent-runs/${id}`)
export const createAgentRun = (payload: Record<string, unknown>) => api<AgentRun>('/api/v1/agent-runs', { method: 'POST', body: JSON.stringify(payload) })
export const agentRunAction = (id: string, action: 'start' | 'pause' | 'cancel', reason?: string) => api<AgentRun>(`/api/v1/agent-runs/${id}/${action}`, { method: 'POST', body: JSON.stringify(reason ? { reason } : {}) })
export const createChangeSet = (runId: string, payload: { branch: string; base_commit: string }) => api<ChangeSet>(`/api/v1/agent-runs/${runId}/change-sets`, { method: 'POST', body: JSON.stringify(payload) })
export const addChangeSetFile = (id: string, payload: { path: string; action: string; diff: string }) => api<ChangeSet>(`/api/v1/change-sets/${id}/files`, { method: 'POST', body: JSON.stringify(payload) })
export const selfReviewChangeSet = (id: string, review: Record<string, unknown>) => api<ChangeSet>(`/api/v1/change-sets/${id}/self-review`, { method: 'POST', body: JSON.stringify({ review }) })
export const submitChangeSet = (id: string) => api<ChangeSet>(`/api/v1/change-sets/${id}/submit`, { method: 'POST', body: JSON.stringify({}) })
export const approveChangeSet = (id: string) => api<ChangeSet>(`/api/v1/change-sets/${id}/approve`, { method: 'POST', body: JSON.stringify({}) })
export const recordVerification = (id: string, payload: Record<string, unknown>) => api<Verification>(`/api/v1/change-sets/${id}/verifications`, { method: 'POST', body: JSON.stringify(payload) })
export const mockups = (projectId: string) => api<Mockup[]>(`/api/v1/design/mockups?project_id=${encodeURIComponent(projectId)}`)
export const createMockup = (payload: Record<string, unknown>) => api<Mockup>('/api/v1/design/mockups', { method: 'POST', body: JSON.stringify(payload) })
export const mockupAction = (id: string, action: 'submit' | 'approve' | 'request-changes') => api<Mockup>(`/api/v1/design/mockups/${id}/${action}`, { method: 'POST', body: JSON.stringify({}) })
export const previews = (projectId: string) => api<Preview[]>(`/api/v1/design/previews?project_id=${encodeURIComponent(projectId)}`)
export const revokePreview = (id: string) => api<Preview>(`/api/v1/design/previews/${id}/revoke`, { method: 'POST', body: JSON.stringify({}) })
export const defects = (projectId: string) => api<Defect[]>(`/api/v1/design/defects?project_id=${encodeURIComponent(projectId)}`)
export const createDefect = (payload: Record<string, unknown>) => api<Defect>('/api/v1/design/defects', { method: 'POST', body: JSON.stringify(payload) })
export const releases = (projectId: string) => api<Release[]>(`/api/v1/releases?project_id=${encodeURIComponent(projectId)}`)
export const release = (id: string) => api<Release>(`/api/v1/releases/${id}`)
export const releaseAction = (id: string, action: 'readiness' | 'approve' | 'package', payload: Record<string, unknown> = {}) => api<Release>(`/api/v1/releases/${id}/${action}`, { method: 'POST', body: JSON.stringify(payload) })
export const deploymentPlans = (releaseId?: string) => api<DeploymentPlan[]>(`/api/v1/deployment-plans${releaseId ? `?release_id=${encodeURIComponent(releaseId)}` : ''}`)
export const deployments = () => api<Deployment[]>('/api/v1/deployments')
export const deployment = (id: string) => api<Deployment>(`/api/v1/deployments/${id}`)
export const createRelease = (payload: Record<string, unknown>) => api<Release>('/api/v1/releases', { method: 'POST', body: JSON.stringify(payload) })
export const createDeploymentPlan = (payload: Record<string, unknown>) => api<DeploymentPlan>('/api/v1/deployment-plans', { method: 'POST', body: JSON.stringify(payload) })
export const deploymentPlanAction = (id: string, action: 'submit' | 'approve') => api<DeploymentPlan>(`/api/v1/deployment-plans/${id}/${action}`, { method: 'POST', body: JSON.stringify({}) })
export const createDeployment = (payload: { deployment_plan_id: string; execute: boolean }) => api<Deployment>('/api/v1/deployments', { method: 'POST', body: JSON.stringify(payload) })
export const rollbackDeployment = (id: string) => api<Deployment>(`/api/v1/deployments/${id}/rollback`, { method: 'POST', body: JSON.stringify({}) })
export const repository = (projectId: string) => api<Repository | null>(`/api/v1/projects/${projectId}/repository`)
export const connectRepository = (projectId: string, payload: { ssh_url: string; scope: string; default_branch: string }) => api<Repository>(`/api/v1/projects/${projectId}/repository`, { method: 'POST', body: JSON.stringify(payload) })
export const repositoryAction = (projectId: string, action: 'test' | 'rotate-key' | 'revoke' | 'sync') => api<Repository>(`/api/v1/projects/${projectId}/repository/${action}`, { method: 'POST', body: JSON.stringify({}) })
export const secrets = () => api<Secret[]>('/api/v1/secrets')
export const createSecret = (payload: { name: string; value: string; purpose?: string }) => api<Secret>('/api/v1/secrets', { method: 'POST', body: JSON.stringify(payload) })
export const secretAction = (id: string, action: 'rotate' | 'revoke' | 'verify', value?: string) => api<Secret>(`/api/v1/secrets/${id}/${action}`, { method: 'POST', body: JSON.stringify(value ? { value } : {}) })
export const sandboxReadiness = () => api<Record<string, unknown>>('/api/v1/sandbox/readiness')
export const sandboxDiagnostic = (payload: Record<string, unknown>) => api<Record<string, unknown>>('/api/v1/sandbox/diagnostic', { method: 'POST', body: JSON.stringify(payload) })
export const sandboxProbe = (payload: Record<string, unknown>) => api<Record<string, unknown>>('/api/v1/sandbox/probe', { method: 'POST', body: JSON.stringify(payload) })
export const createPreview = (payload: Record<string, unknown>) => api<Preview>('/api/v1/design/previews', { method: 'POST', body: JSON.stringify(payload) })
export const createAcceptanceSession = (payload: Record<string, unknown>) => api<AcceptanceSession>('/api/v1/design/acceptance/sessions', { method: 'POST', body: JSON.stringify(payload) })
export const acceptanceSession = (id: string) => api<AcceptanceSession>(`/api/v1/design/acceptance/sessions/${id}`)
export const recordAcceptanceResult = (id: string, payload: Record<string, unknown>) => api<AcceptanceSession>(`/api/v1/design/acceptance/sessions/${id}/results`, { method: 'POST', body: JSON.stringify(payload) })
export const completeAcceptanceSession = (id: string, evidence: Record<string, unknown>) => api<AcceptanceSession>(`/api/v1/design/acceptance/sessions/${id}/complete`, { method: 'POST', body: JSON.stringify(evidence) })
export const auditEvents = () => api<{ total: number; events: unknown[] }>('/api/v1/audit/events')
export const auditVerify = () => api<Record<string, unknown>>('/api/v1/audit/verify')
export const diagnosticBundle = () => api<Record<string, unknown>>('/api/v1/diagnostics/bundle')
export const retentionPlan = () => api<Record<string, unknown>>('/api/v1/diagnostics/retention-plan')
export const executeRetention = (payload: { dry_run: boolean; confirm?: boolean }) => api<Record<string, unknown>>('/api/v1/diagnostics/retention/execute', { method: 'POST', body: JSON.stringify(payload) })
export const auditExport = () => api<{ count: number; events: unknown[] }>('/api/v1/audit/export')
async function generatedGet<T>(path: '/health/live' | '/health/ready' | '/health/metrics'): Promise<T> {
  const result = path === '/health/live' ? await generatedClient.GET('/health/live') : path === '/health/ready' ? await generatedClient.GET('/health/ready') : await generatedClient.GET('/health/metrics')
  if (result.error || !result.response.ok) throw new ApiError('The health request could not be completed.', result.response.status, 'health_error')
  return ((result.data as { data?: T }).data ?? result.data) as T
}
export const healthLive = () => generatedGet<Record<string, unknown>>('/health/live')
export const healthReady = () => generatedGet<Record<string, unknown>>('/health/ready')
export const healthMetrics = () => generatedGet<Record<string, unknown>>('/health/metrics')
export const traceLinks = () => api<TraceLink[]>('/api/v1/traceability/links')
export const createTraceLink = (payload: { source_type: string; target_type: string; relation: string; source_id: string; target_id: string }) => api<TraceLink>('/api/v1/traceability/links', { method: 'POST', body: JSON.stringify(payload) })
export const deleteTraceLink = (id: string) => api<{ deleted: boolean; id: string }>(`/api/v1/traceability/links/${id}`, { method: 'DELETE' })
export const traceSearch = (query: string) => api<unknown[]>(`/api/v1/traceability/search?q=${encodeURIComponent(query)}`)
