$ErrorActionPreference = "Stop"

$compose = @("-f", "docker-compose.yml", "-f", "docker-compose.e2e.yml", "-p", "botq-e2e")
$password = if ($env:POSTGRES_PASSWORD) { $env:POSTGRES_PASSWORD } else { "BotqE2e-$(New-Guid)" }
$env:POSTGRES_PASSWORD = $password
$env:BOTQ_E2E_PORT = if ($env:BOTQ_E2E_PORT) { $env:BOTQ_E2E_PORT } else { "18081" }
$env:BOTQ_E2E_BASE_URL = if ($env:BOTQ_E2E_BASE_URL) { $env:BOTQ_E2E_BASE_URL } else { "http://127.0.0.1:$env:BOTQ_E2E_PORT" }
$env:BOTQ_E2E_ORG = if ($env:BOTQ_E2E_ORG) { $env:BOTQ_E2E_ORG } else { "acme" }
$env:BOTQ_E2E_PASSWORD = if ($env:BOTQ_E2E_PASSWORD) { $env:BOTQ_E2E_PASSWORD } else { "E2ePass!2026" }
$env:BOTQ_E2E_ADMIN_EMAIL = if ($env:BOTQ_E2E_ADMIN_EMAIL) { $env:BOTQ_E2E_ADMIN_EMAIL } else { "admin@acme.local" }
$env:BOTQ_E2E_REVIEWER_EMAIL = if ($env:BOTQ_E2E_REVIEWER_EMAIL) { $env:BOTQ_E2E_REVIEWER_EMAIL } else { "reviewer@acme.local" }

try {
    docker compose @compose up -d --build db api worker proxy
    docker compose @compose exec -T api flask db upgrade
    docker compose @compose exec -T api flask bootstrap --org-name E2E-Organization --slug $env:BOTQ_E2E_ORG --email $env:BOTQ_E2E_ADMIN_EMAIL --password $env:BOTQ_E2E_PASSWORD
    docker compose @compose exec -T api sh -c "PYTHONPATH=/srv/botq python scripts/seed_e2e.py"

    $ready = $false
    $deadline = (Get-Date).AddSeconds(90)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-RestMethod -Uri "$env:BOTQ_E2E_BASE_URL/health/ready" -TimeoutSec 5
            if ($response.data.status -eq "ready") {
                $ready = $true
                break
            }
        } catch {
            # The proxy may need a few seconds after the API container starts.
        }
        Start-Sleep -Seconds 2
    }
    if (-not $ready) { throw "Dockerized botq API did not become ready within 90 seconds." }

    python -m pytest e2e -q
    if ($LASTEXITCODE -ne 0) { throw "E2E pytest failed with exit code $LASTEXITCODE." }
}
catch {
    Write-Host "E2E failed; collecting API and proxy logs before teardown."
    docker compose @compose logs --no-color api proxy
    throw
}
finally {
    docker compose @compose down -v --remove-orphans
}
