#Requires -Version 7.0
<#
.SYNOPSIS
  Phase 1 Gate 1 validation: clone a pilot repository from a real SSH Git remote
  using the actual GitCommandBackend (no fakes).

.DESCRIPTION
  Drives the running Docker Compose stack (plus the optional "git-validation"
  profile git-fixture service) through: connect -> provision deploy key ->
  host-key scan -> test (ls-remote) -> sync (clone) -> server change -> sync
  (fetch) -> rotate key -> test -> revoke. Exits non-zero on any failed step.

.NOTES
  Start the stack first:
    docker compose --profile git-validation up -d --build
    docker compose exec api flask db upgrade
    docker compose exec api flask bootstrap --org-name "Acme" --slug "acme" --email "admin@acme.local" --password "S3curePass!"
#>
param(
    [string]$Base = "http://localhost:8884",
    [string]$Email = "admin@acme.local",
    [string]$Password = "S3curePass!",
    [string]$Organization = "acme",
    [string]$SshUrl = "git@git-fixture:/srv/git/pilot.git",
    [string]$Fixture = "git-fixture",
    [string]$ProjectKey = "pilotrepo",
    [string]$Branch = "main"
)

$ErrorActionPreference = "Stop"
$script:failed = $false
$script:token = $null
$script:projectId = $null
$script:deployKey = $null
$script:head1 = $null
$script:head2 = $null
$script:workspace = $null

function Step($name, [scriptblock]$body) {
    try {
        & $body
        Write-Host "PASS  $name" -ForegroundColor Green
    }
    catch {
        $script:failed = $true
        Write-Host "FAIL  $name :: $($_.Exception.Message)" -ForegroundColor Red
    }
}

function ApiGet($path) {
    (Invoke-RestMethod -Uri "$Base$path" -Headers @{ Authorization = "Bearer $script:token" })
}
function ApiPost($path, $body) {
    (Invoke-RestMethod -Uri "$Base$path" -Method Post -Headers @{ Authorization = "Bearer $script:token" } `
        -ContentType "application/json" -Body ($body | ConvertTo-Json -Compress))
}
function Fixture($cmd) { docker compose exec -T $Fixture sh -c $cmd }
function Assert($cond, $msg) { if (-not $cond) { throw $msg } }

Write-Host "=== Phase 1 pilot-clone validation against $Base ===" -ForegroundColor Cyan

# 1. login
Step "login" {
    $login = Invoke-RestMethod -Uri "$Base/api/v1/auth/login" -Method Post `
        -ContentType "application/json" `
        -Body (@{ email = $Email; password = $Password; organization = $Organization } | ConvertTo-Json -Compress)
    $script:token = $login.data.token
    Assert ($script:token) "no token returned"
}

# 2. create a project to own the repository connection
Step "create project" {
    try {
        $created = ApiPost "/api/v1/projects" @{ name = "Pilot Repo"; key = $ProjectKey; default_branch = $Branch }
        $script:projectId = $created.data.id
    }
    catch {
        $listing = ApiGet "/api/v1/projects"
        $match = $listing.data | Where-Object { $_.key -eq $ProjectKey }
        Assert ($match) "could not create or find project '$ProjectKey'"
        $script:projectId = $match.id
    }
    Assert ($script:projectId) "project id missing"
}

# 3. connect repository (provision deploy key + scan host key)
Step "connect repository (provision key + host-key scan)" {
    try {
        $conn = ApiPost "/api/v1/projects/$script:projectId/repository" @{
            ssh_url = $SshUrl; scope = "rw"; default_branch = $Branch
        }
    } catch {
        $rotated = ApiPost "/api/v1/projects/$script:projectId/repository/rotate-key" @{}
        $conn = $rotated
    }
    $script:deployKey = $conn.data.deploy_key_public
    Assert ($script:deployKey -like "ssh-ed25519*") "no ed25519 deploy key returned"
    Assert ($conn.data.host -eq $Fixture) "unexpected host: $($conn.data.host)"
}

# 4. install the deploy key on the server (mirrors adding it in GitHub)
Step "install deploy key on git server" {
    $oneLine = ($script:deployKey -join " ").Trim()
    Fixture "echo '$oneLine' >> /home/git/.ssh/authorized_keys && chmod 600 /home/git/.ssh/authorized_keys"
    $count = (Fixture "grep -c . /home/git/.ssh/authorized_keys").Trim()
    Assert ([int]$count -ge 1) "deploy key not installed"
}

# 5. connection test (git ls-remote over SSH)
Step "test connection (ls-remote)" {
    $tested = ApiPost "/api/v1/projects/$script:projectId/repository/test" @{}
    Assert ($tested.data.status -eq "active") "status not active: $($tested.data.status) $($tested.data.last_error)"
}

# 6. sync -> clone the pilot repo into an isolated workspace
Step "sync #1 (clone)" {
    $synced = ApiPost "/api/v1/projects/$script:projectId/repository/sync" @{}
    $script:head1 = $synced.data.head
    $script:workspace = $synced.data.workspace
    Assert ($script:head1 -and $script:head1.Length -eq 40) "no head sha"
    Assert ($synced.data.host_fingerprint_verified) "host fingerprint not verified"
    $exists = docker compose exec -T api sh -c "test -d '$script:workspace/.git' && echo yes || echo no"
    Assert ($exists.Trim() -eq "yes") "clone working tree not found at $script:workspace"
}

# 7. push a new commit to the server (locally), then sync again (fetch over SSH)
Step "sync #2 (fetch server update)" {
    Fixture "git config --global --add safe.directory '*' && cd /tmp && rm -rf push && git clone -q /srv/git/pilot.git push && cd push && git config user.email v@x && git config user.name v && echo change >> NOTES.md && git add NOTES.md && git commit -q -m 'server update' && git push -q origin HEAD:$Branch"
    $serverHead = (Fixture "git --git-dir=/srv/git/pilot.git rev-parse $Branch").Trim()
    $synced = ApiPost "/api/v1/projects/$script:projectId/repository/sync" @{}
    $script:head2 = $synced.data.head
    Assert ($script:head2 -eq $serverHead) "synced head ($script:head2) != server head ($serverHead)"
    Assert ($script:head2 -ne $script:head1) "head did not advance after fetch"
}

# 8. rotate the deploy key and re-test (server gets the new key -> old revoked)
Step "rotate key + retest" {
    $rotated = ApiPost "/api/v1/projects/$script:projectId/repository/rotate-key" @{}
    $newKey = ($rotated.data.deploy_key_public -join " ").Trim()
    Assert ($newKey) "no key after rotate"
    Fixture "echo '$newKey' > /home/git/.ssh/authorized_keys && chmod 600 /home/git/.ssh/authorized_keys"
    $tested = ApiPost "/api/v1/projects/$script:projectId/repository/test" @{}
    Assert ($tested.data.status -eq "active") "retest after rotate failed: $($tested.data.last_error)"
}

# 9. revoke removes local key material and the connection stops working
Step "revoke (access revoked)" {
    ApiPost "/api/v1/projects/$script:projectId/repository/revoke" @{} | Out-Null
    Fixture ": > /home/git/.ssh/authorized_keys"
    try {
        ApiPost "/api/v1/projects/$script:projectId/repository/test" @{} | Out-Null
        throw "test unexpectedly succeeded after revoke"
    } catch {
        if ($_.Exception.Message -like "*unexpectedly succeeded*") { throw }
        Write-Host "      (post-revoke connection test correctly rejected)"
    }
}

# 10. audit trail records the full lifecycle
Step "audit trail records lifecycle" {
    $verify = ApiGet "/api/v1/audit/verify"
    Assert ($verify.data.verified) "audit chain not verified"
    $page = ApiGet "/api/v1/audit/events?limit=200"
    $actions = $page.data.events | ForEach-Object { $_.action } | Sort-Object -Unique
    foreach ($needed in @("repository.connected", "repository.tested", "repository.synced", "repository.key_rotated", "repository.key_revoked")) {
        Assert ($actions -contains $needed) "missing audit action: $needed"
    }
}

Write-Host ""
if ($script:failed) {
    Write-Host "RESULT: Phase 1 pilot-clone validation FAILED" -ForegroundColor Red
    exit 1
}
Write-Host "RESULT: Phase 1 pilot-clone validation PASSED (head $script:head1 -> $script:head2 over real SSH)" -ForegroundColor Green
