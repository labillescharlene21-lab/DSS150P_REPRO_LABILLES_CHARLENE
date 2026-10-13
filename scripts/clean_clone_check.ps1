<#
 Proves the repository is reproducible from a CLEAN clone (brief section 5 / acceptance test A1).
 It clones the repo into a temp folder, places the dataset, copies .env.example to .env, builds and starts the
 services with Docker Compose, runs the whole pipeline twice, verifies the database and runs the tests inside
 the container. The transcript is saved to docs\evidence\clean_clone.txt of THIS repository.

 Usage (from the repository root):   powershell -ExecutionPolicy Bypass -File scripts\clean_clone_check.ps1
 The repository must be pushed first: it clones from GitHub, not from your working folder.
#>
param(
    [string]$RepoUrl = "https://github.com/labillescharlene21-lab/DSS150P_REPRO_LABILLES_CHARLENE.git",
    [string]$Dataset = "data\source\Stroke_Prediction_Dataset.csv",
    [int]$HostPort = 5434          # different from the main stack so both can run side by side
)
$ErrorActionPreference = "Stop"
$origin = (Get-Location).Path
$evidence = Join-Path $origin "docs\evidence"
New-Item -ItemType Directory -Force -Path $evidence | Out-Null
$datasetPath = Join-Path $origin $Dataset
if (-not (Test-Path $datasetPath)) { throw "Dataset not found at $datasetPath" }

Start-Transcript -Path (Join-Path $evidence "clean_clone.txt") -Force | Out-Null
$work = Join-Path $env:TEMP "dss150p_clean_clone"
$env:COMPOSE_PROJECT_NAME = "dss150p_cleanclone"
try {
    Write-Host "== 1. clean clone into $work"
    if (Test-Path $work) { Remove-Item -Recurse -Force $work }
    git clone $RepoUrl $work
    Set-Location $work
    git log --oneline | Select-Object -First 15

    Write-Host "== 2. secrets are not in the clone"
    if (Test-Path ".env") { throw ".env was committed" }
    if (git ls-files .env) { throw ".env is tracked" }

    Write-Host "== 3. place the dataset and verify its checksum against the manifest"
    New-Item -ItemType Directory -Force -Path "data\source" | Out-Null
    Copy-Item $datasetPath "data\source\Stroke_Prediction_Dataset.csv"
    $actual = (Get-FileHash "data\source\Stroke_Prediction_Dataset.csv" -Algorithm SHA256).Hash.ToLower()
    $expected = ((Select-String -Path "metadata\source_manifest.yml" -Pattern "sha256:\s*(\S+)").Matches[0].Groups[1].Value).Trim("'`"").ToLower()
    if ($actual -ne $expected) { throw "checksum mismatch: $actual vs $expected" }
    Write-Host "checksum OK: $actual"

    Write-Host "== 4. .env from the example, only the host port changes"
    (Get-Content ".env.example") -replace '^POSTGRES_PORT=.*', "POSTGRES_PORT=$HostPort" |
        Set-Content ".env" -Encoding ascii

    Write-Host "== 5. build and start PostgreSQL; wait for the healthcheck"
    docker compose up -d postgres
    for ($i = 0; $i -lt 30; $i++) {
        $state = docker compose ps --format json postgres | ConvertFrom-Json | Select-Object -ExpandProperty Health
        if ($state -eq "healthy") { break }
        Start-Sleep -Seconds 3
    }
    if ($state -ne "healthy") { throw "postgres did not become healthy" }
    docker compose build pipeline

    Write-Host "== 6. full pipeline, then a second (incremental) run"
    docker compose run --rm pipeline python -m src.cli run-all --run-id clean-clone-1
    if ($LASTEXITCODE -ne 0) { throw "first run failed" }
    docker compose run --rm pipeline python -m src.cli run-all --run-id clean-clone-2 --incremental
    if ($LASTEXITCODE -ne 0) { throw "second run failed" }

    Write-Host "== 7. no duplicate logical records"
    docker compose run --rm pipeline python -m src.cli verify-db
    if ($LASTEXITCODE -ne 0) { throw "verify-db failed" }

    Write-Host "== 8. baseline vs reproduced, then the tests inside the container"
    docker compose run --rm pipeline python -m src.cli compare
    Get-Content "docs\metrics_comparison.md" | Select-Object -First 14
    docker compose run --rm pipeline python -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw "tests failed" }

    Write-Host "CLEAN CLONE OK"
}
finally {
    Set-Location $origin
    docker compose -p dss150p_cleanclone -f (Join-Path $work "docker-compose.yml") down -v 2>$null
    Stop-Transcript | Out-Null
}
