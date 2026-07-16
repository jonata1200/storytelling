[CmdletBinding()]
param(
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 8000,
    [switch]$SkipDocker,
    [switch]$SkipMigrations,
    [switch]$Background
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $ProjectRoot

function Get-ProjectPython {
    $venvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
        return $venvPython
    }

    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $pythonCommand) {
        throw "Python nao encontrado. Crie o ambiente com: python -m venv .venv"
    }
    return $pythonCommand.Source
}

function Get-DockerExecutable {
    $dockerCommand = Get-Command docker -ErrorAction SilentlyContinue
    if ($null -ne $dockerCommand) {
        return $dockerCommand.Source
    }

    $dockerDesktopPath = "C:\Program Files\Docker\Docker\resources\bin\docker.exe"
    if (Test-Path $dockerDesktopPath) {
        return $dockerDesktopPath
    }

    throw "Docker nao encontrado no PATH. Abra o Docker Desktop e reinicie o terminal."
}

function Invoke-DockerCompose {
    param([string[]]$ComposeArguments)

    $docker = Get-DockerExecutable
    & $docker compose @ComposeArguments
}

$python = Get-ProjectPython

if (-not (Test-Path ".env")) {
    Write-Warning "Arquivo .env nao encontrado. Crie com: Copy-Item .env.example .env"
}

if (-not $SkipDocker) {
    Write-Host "Iniciando PostgreSQL e Redis com Docker Compose..."
    Invoke-DockerCompose -ComposeArguments @("up", "-d")
}

if (-not $SkipMigrations) {
    Write-Host "Aplicando migrations do Alembic..."
    & $python -m alembic upgrade head
}

$url = "http://${HostAddress}:$Port"
$uvicornArguments = @(
    "-m",
    "uvicorn",
    "app.main:app",
    "--host",
    $HostAddress,
    "--port",
    $Port.ToString(),
    "--reload"
)

if ($Background) {
    $runtimeDir = Join-Path $ProjectRoot ".runtime"
    New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
    $stdoutLog = Join-Path $runtimeDir "uvicorn.out.log"
    $stderrLog = Join-Path $runtimeDir "uvicorn.err.log"
    $pidFile = Join-Path $runtimeDir "uvicorn.pid"

    $process = Start-Process `
        -FilePath $python `
        -ArgumentList $uvicornArguments `
        -WorkingDirectory $ProjectRoot `
        -RedirectStandardOutput $stdoutLog `
        -RedirectStandardError $stderrLog `
        -PassThru `
        -WindowStyle Hidden

    Set-Content -Path $pidFile -Value $process.Id
    Write-Host "Aplicacao iniciada em segundo plano: $url"
    Write-Host "PID: $($process.Id)"
    Write-Host "Logs: $stdoutLog e $stderrLog"
    exit 0
}

Write-Host "Iniciando aplicacao em primeiro plano: $url"
Write-Host "Para finalizar, pressione Ctrl+C ou execute: .\scripts\finalizar.ps1"
& $python @uvicornArguments
