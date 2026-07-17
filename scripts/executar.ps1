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
    $dockerDirectory = Split-Path -Parent $docker
    $originalPath = $env:PATH
    try {
        # O Docker CLI invoca helpers (como docker-credential-desktop) pelo PATH.
        # Quando docker.exe foi localizado pelo fallback, sua pasta pode nao estar nele.
        if (($env:PATH -split ";") -notcontains $dockerDirectory) {
            $env:PATH = "$dockerDirectory;$env:PATH"
        }
        & $docker compose @ComposeArguments
        if ($LASTEXITCODE -ne 0) {
            throw "Docker Compose falhou com codigo de saida $LASTEXITCODE."
        }
    } finally {
        $env:PATH = $originalPath
    }
}

function Wait-PostgresReady {
    param(
        [int]$MaxAttempts = 30,
        [int]$IntervalSeconds = 2
    )

    $docker = Get-DockerExecutable
    Write-Host "Aguardando PostgreSQL ficar pronto..."
    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
        & $docker inspect `
            --format "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}" `
            storytelling-postgres 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) {
            $status = & $docker inspect `
                --format "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}" `
                storytelling-postgres 2>$null
            if ($status -eq "healthy") {
                Write-Host "PostgreSQL pronto."
                return
            }
        }
        Start-Sleep -Seconds $IntervalSeconds
    }
    throw "PostgreSQL nao ficou pronto dentro do tempo esperado. Consulte: docker compose logs postgres"
}

function Stop-PreviousStorytellingServer {
    param(
        [int]$ServerPort,
        [object[]]$Listeners
    )

    try {
        $health = Invoke-RestMethod `
            -Uri "http://127.0.0.1:$ServerPort/api/v1/health/live" `
            -TimeoutSec 3 `
            -ErrorAction Stop
    } catch {
        return $false
    }

    if ([string]$health.app -notlike "Storytelling*") {
        return $false
    }

    $ownerIds = $Listeners |
        Select-Object -ExpandProperty OwningProcess -Unique
    Write-Host "Encerrando instancia anterior da aplicacao na porta $ServerPort..."
    foreach ($ownerId in $ownerIds) {
        $process = Get-Process -Id $ownerId -ErrorAction SilentlyContinue
        if ($null -ne $process) {
            try {
                Stop-Process -Id $ownerId -Force -ErrorAction Stop
                continue
            } catch {
                Write-Warning "O PID $ownerId exige permissao de administrador."
            }
        }

        Write-Host "Solicitando permissao do Windows para finalizar o PID $ownerId..."
        try {
            $elevatedKill = Start-Process `
                -FilePath "$env:SystemRoot\System32\taskkill.exe" `
                -ArgumentList @("/PID", $ownerId.ToString(), "/T", "/F") `
                -Verb RunAs `
                -Wait `
                -PassThru
            if ($elevatedKill.ExitCode -ne 0) {
                Write-Warning "O Windows nao conseguiu finalizar o PID $ownerId."
            }
        } catch {
            Write-Warning "A autorizacao para finalizar o PID $ownerId foi cancelada ou negada."
        }
    }

    for ($attempt = 1; $attempt -le 10; $attempt++) {
        Start-Sleep -Milliseconds 500
        $remaining = Get-NetTCPConnection `
            -LocalPort $ServerPort `
            -State Listen `
            -ErrorAction SilentlyContinue
        if ($null -eq $remaining) {
            Write-Host "Instancia anterior encerrada."
            return $true
        }
    }
    return $false
}

function Get-NextAvailablePort {
    param(
        [int]$StartPort,
        [int]$MaxAttempts = 20
    )

    for ($candidate = $StartPort; $candidate -lt ($StartPort + $MaxAttempts); $candidate++) {
        $listener = Get-NetTCPConnection `
            -LocalPort $candidate `
            -State Listen `
            -ErrorAction SilentlyContinue
        if ($null -eq $listener) {
            return $candidate
        }
    }
    throw "Nenhuma porta livre encontrada entre $StartPort e $($StartPort + $MaxAttempts - 1)."
}

$python = Get-ProjectPython

if (-not (Test-Path ".env")) {
    if (Test-Path ".env.example") {
        Copy-Item ".env.example" ".env"
        Write-Host "Arquivo .env criado a partir de .env.example."
    } else {
        Write-Warning "Arquivo .env nao encontrado e .env.example nao existe."
    }
}

if (-not $SkipDocker) {
    Write-Host "Iniciando PostgreSQL e Redis com Docker Compose..."
    Invoke-DockerCompose -ComposeArguments @("up", "-d")
    Wait-PostgresReady
}

if (-not $SkipMigrations) {
    Write-Host "Aplicando migrations do Alembic..."
    & $python -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) {
        throw "As migrations do Alembic falharam com codigo de saida $LASTEXITCODE."
    }
}

$existingListener = Get-NetTCPConnection `
    -LocalPort $Port `
    -State Listen `
    -ErrorAction SilentlyContinue
if ($null -ne $existingListener) {
    $stoppedPreviousServer = Stop-PreviousStorytellingServer `
        -ServerPort $Port `
        -Listeners $existingListener
    if (-not $stoppedPreviousServer) {
        $ownerIds = $existingListener |
            Select-Object -ExpandProperty OwningProcess -Unique
        $requestedPort = $Port
        $Port = Get-NextAvailablePort -StartPort ($requestedPort + 1)
        Write-Warning (
            "Nao foi possivel encerrar o processo PID $($ownerIds -join ', ') " +
            "na porta $requestedPort. A aplicacao sera iniciada automaticamente na porta $Port."
        )
    }
}

$url = "http://${HostAddress}:$Port"
$uvicornArguments = @(
    "-m",
    "uvicorn",
    "app.main:app",
    "--host",
    $HostAddress,
    "--port",
    $Port.ToString()
)

if ($Background) {
    $runtimeDir = Join-Path $ProjectRoot ".runtime"
    New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
    $stdoutLog = Join-Path $runtimeDir "uvicorn.out.log"
    $stderrLog = Join-Path $runtimeDir "uvicorn.err.log"
    $pidFile = Join-Path $runtimeDir "uvicorn-$Port.pid"

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

$uvicornArguments += "--reload"
Write-Host "Iniciando aplicacao em primeiro plano: $url"
Write-Host "Para finalizar, pressione Ctrl+C ou execute: .\scripts\finalizar.ps1"
& $python @uvicornArguments
