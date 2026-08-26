[CmdletBinding()]
param(
    [ValidateSet("run", "stop", "restart", "tools")]
    [string]$Command = "run",
    [ValidateSet("", "status", "logs", "test", "check", "migrate", "clean")]
    [string]$Tool = "",
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 8000,
    [int]$PortRangeEnd = 8020,
    [Alias("SkipDocker")]
    [switch]$NoDocker,
    [Alias("SkipMigrations")]
    [switch]$NoMigrate,
    [switch]$Dev,
    [switch]$Background,
    [switch]$KeepDocker,
    [switch]$Follow
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $ProjectRoot

function Write-Step {
    param([string]$Message)
    Write-Host "==> $Message"
}

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

    return $null
}

function Invoke-DockerCompose {
    param([string[]]$ComposeArguments)

    $docker = Get-DockerExecutable
    if ($null -eq $docker) {
        throw "Docker nao encontrado no PATH. Abra o Docker Desktop e reinicie o terminal."
    }

    $dockerDirectory = Split-Path -Parent $docker
    $originalPath = $env:PATH
    try {
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
    if ($null -eq $docker) {
        throw "Docker nao encontrado."
    }

    Write-Step "Aguardando PostgreSQL"
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
    throw "PostgreSQL nao ficou pronto dentro do tempo esperado."
}

function Test-AppHealth {
    param([int]$CandidatePort)

    try {
        $health = Invoke-RestMethod `
            -Uri "http://127.0.0.1:$CandidatePort/api/v1/health/live" `
            -TimeoutSec 1 `
            -ErrorAction Stop
        return ([string]$health.app -like "Storytelling*")
    } catch {
        return $false
    }
}

function Get-ListeningProcessIds {
    param([int]$CandidatePort)

    $connections = Get-NetTCPConnection `
        -LocalPort $CandidatePort `
        -State Listen `
        -ErrorAction SilentlyContinue
    if ($null -eq $connections) {
        return @()
    }
    return @($connections | Select-Object -ExpandProperty OwningProcess -Unique)
}

function Stop-ProcessSafely {
    param(
        [int]$ProcessId,
        [string]$Description
    )

    $process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if ($null -eq $process) {
        return $false
    }

    try {
        Write-Host "Finalizando $Description (PID $ProcessId)..."
        Stop-Process -Id $ProcessId -Force -ErrorAction Stop
        return $true
    } catch {
        Write-Warning "Nao foi possivel finalizar o PID $ProcessId sem permissao elevada."
        return $false
    }
}

function Stop-App {
    $runtimeDir = Join-Path $ProjectRoot ".runtime"
    $stoppedIds = [System.Collections.Generic.HashSet[int]]::new()
    $stoppedPorts = [System.Collections.Generic.HashSet[int]]::new()

    if (Test-Path $runtimeDir) {
        $pidFiles = Get-ChildItem -Path $runtimeDir -Filter "*.pid" -File -ErrorAction SilentlyContinue
        foreach ($pidFile in $pidFiles) {
            $pidValue = Get-Content $pidFile.FullName -ErrorAction SilentlyContinue |
                Select-Object -First 1
            if ($pidValue -match "^\d+$") {
                $numericPid = [int]$pidValue
                $description = if ($pidFile.Name -eq "storytelling-worker.pid") {
                    "worker local registrado"
                } else {
                    "Storytelling registrado"
                }
                if (Stop-ProcessSafely -ProcessId $numericPid -Description $description) {
                    [void]$stoppedIds.Add($numericPid)
                }
            }
            Remove-Item -LiteralPath $pidFile.FullName -Force -ErrorAction SilentlyContinue
        }
    }

    $lastPort = [Math]::Max($Port, $PortRangeEnd)
    foreach ($candidatePort in $Port..$lastPort) {
        if (-not (Test-AppHealth -CandidatePort $candidatePort)) {
            continue
        }
        foreach ($processId in Get-ListeningProcessIds -CandidatePort $candidatePort) {
            if ($stoppedIds.Contains([int]$processId)) {
                continue
            }
            if (Stop-ProcessSafely -ProcessId ([int]$processId) -Description "Storytelling na porta $candidatePort") {
                [void]$stoppedIds.Add([int]$processId)
                [void]$stoppedPorts.Add($candidatePort)
            }
        }
    }

    Write-Host (
        "Instancias finalizadas: $($stoppedIds.Count). " +
        "Portas liberadas: $(if ($stoppedPorts.Count) { $stoppedPorts -join ', ' } else { 'nenhuma' })."
    )
}

function Stop-Stack {
    Stop-App
    if ($KeepDocker) {
        Write-Host "Containers mantidos em execucao."
        return
    }

    $docker = Get-DockerExecutable
    if ($null -eq $docker) {
        Write-Warning "Docker nao encontrado. A aplicacao foi finalizada, mas containers nao foram alterados."
        return
    }

    Write-Step "Parando containers"
    & $docker compose stop
}

function Get-NextAvailablePort {
    param([int]$StartPort)

    for ($candidate = $StartPort; $candidate -le $PortRangeEnd; $candidate++) {
        $listener = Get-NetTCPConnection `
            -LocalPort $candidate `
            -State Listen `
            -ErrorAction SilentlyContinue
        if ($null -eq $listener) {
            return $candidate
        }
    }
    throw "Nenhuma porta livre encontrada entre $StartPort e $PortRangeEnd."
}

function Ensure-EnvironmentFile {
    if (Test-Path ".env") {
        return
    }
    if (-not (Test-Path ".env.example")) {
        Write-Warning "Arquivo .env nao encontrado e .env.example nao existe."
        return
    }
    Copy-Item ".env.example" ".env"
    Write-Host "Arquivo .env criado a partir de .env.example."
}

function Invoke-Migrations {
    $python = Get-ProjectPython
    Write-Step "Aplicando migrations"
    & $python -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) {
        throw "As migrations do Alembic falharam com codigo de saida $LASTEXITCODE."
    }
}

function Wait-AppReady {
    param([int]$CandidatePort)

    for ($attempt = 1; $attempt -le 30; $attempt++) {
        if (Test-AppHealth -CandidatePort $CandidatePort) {
            return $true
        }
        Start-Sleep -Seconds 1
    }
    return $false
}

function Start-LocalWorker {
    $python = Get-ProjectPython
    $runtimeDir = Join-Path $ProjectRoot ".runtime"
    New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
    $pidFile = Join-Path $runtimeDir "storytelling-worker.pid"

    if (Test-Path $pidFile) {
        $existingPid = Get-Content $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($existingPid -match "^\d+$" -and (Get-Process -Id ([int]$existingPid) -ErrorAction SilentlyContinue)) {
            Write-Host "Worker local ja esta em execucao (PID $existingPid)."
            return
        }
        Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
    }

    $stdoutLog = Join-Path $runtimeDir "worker.out.log"
    $stderrLog = Join-Path $runtimeDir "worker.err.log"
    $process = Start-Process `
        -FilePath $python `
        -ArgumentList @("-m", "app.workers.main") `
        -WorkingDirectory $ProjectRoot `
        -RedirectStandardOutput $stdoutLog `
        -RedirectStandardError $stderrLog `
        -PassThru `
        -WindowStyle Hidden
    Set-Content -Path $pidFile -Value $process.Id
    Write-Host "Worker local iniciado (PID $($process.Id))."
}

function Start-App {
    param(
        [switch]$Reload,
        [switch]$AsBackground
    )

    $python = Get-ProjectPython
    Ensure-EnvironmentFile

    if (-not $NoDocker) {
        Write-Step "Subindo PostgreSQL e Redis"
        Invoke-DockerCompose -ComposeArguments @("up", "-d", "postgres", "redis")
        Wait-PostgresReady
    }

    if (-not $NoMigrate) {
        Invoke-Migrations
    }

    if (Test-AppHealth -CandidatePort $Port) {
        Write-Step "Reiniciando instancia existente na porta $Port"
        Stop-App
    } elseif ((Get-ListeningProcessIds -CandidatePort $Port).Count -gt 0) {
        $requestedPort = $Port
        $script:Port = Get-NextAvailablePort -StartPort ($requestedPort + 1)
        Write-Warning "Porta $requestedPort ocupada por outro servico; usando porta $Port."
    }

    Start-LocalWorker

    $url = "http://${HostAddress}:$Port"
    $uvicornArguments = @(
        "-m",
        "app.server",
        "--host",
        $HostAddress,
        "--port",
        $Port.ToString()
    )

    if ($Reload) {
        $uvicornArguments += "--reload"
    }

    if (-not $AsBackground) {
        $mode = if ($Reload) { "modo dev" } else { "primeiro plano" }
        Write-Step "Iniciando aplicacao em ${mode}: $url"
        Write-Host "Logs e erros ficarao visiveis neste terminal."
        Write-Host "Para finalizar, pressione Ctrl+C."
        & $python @uvicornArguments
        return
    }

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

    if (-not (Wait-AppReady -CandidatePort $Port)) {
        Write-Warning "A aplicacao nao respondeu no tempo esperado. Consulte: .\scripts\story.ps1 tools logs"
        Set-Content -Path $pidFile -Value $process.Id
        return
    }

    $listenerIds = Get-ListeningProcessIds -CandidatePort $Port
    $serverPid = if ($listenerIds.Count -gt 0) { [int]$listenerIds[0] } else { $process.Id }
    Set-Content -Path $pidFile -Value $serverPid

    Write-Host "Aplicacao iniciada: $url"
    Write-Host "PID: $serverPid"
    Write-Host "Logs: .runtime\uvicorn.out.log e .runtime\uvicorn.err.log"
}

function Show-Status {
    $found = $false
    foreach ($candidatePort in $Port..$PortRangeEnd) {
        if (Test-AppHealth -CandidatePort $candidatePort) {
            $found = $true
            Write-Host "Storytelling online: http://127.0.0.1:$candidatePort"
            break
        }
    }
    if (-not $found) {
        Write-Host "Storytelling offline nas portas $Port-$PortRangeEnd."
    }

    if (-not $NoDocker) {
        $docker = Get-DockerExecutable
        if ($null -ne $docker) {
            try {
                & $docker compose ps
            } catch {
                Write-Warning "Nao foi possivel consultar Docker Compose: $($_.Exception.Message)"
            }
        }
    }
}

function Show-Logs {
    $runtimeDir = Join-Path $ProjectRoot ".runtime"
    $logFiles = @(
        (Join-Path $runtimeDir "uvicorn.err.log"),
        (Join-Path $runtimeDir "uvicorn.out.log"),
        (Join-Path $runtimeDir "worker.err.log"),
        (Join-Path $runtimeDir "worker.out.log")
    ) | Where-Object { Test-Path $_ }

    if (-not $logFiles) {
        Write-Host "Nenhum log encontrado em .runtime."
        return
    }

    foreach ($logFile in $logFiles) {
        Write-Host ""
        Write-Host "### $logFile"
        if ($Follow) {
            Get-Content -Path $logFile -Tail 80 -Wait
        } else {
            Get-Content -Path $logFile -Tail 80
        }
    }
}

function Clean-Runtime {
    Stop-App
    $runtimeDir = Join-Path $ProjectRoot ".runtime"
    if (-not (Test-Path $runtimeDir)) {
        Write-Host "Nada para limpar."
        return
    }

    $targets = Get-ChildItem -Path $runtimeDir -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Extension -in ".log", ".pid" }
    foreach ($target in $targets) {
        Remove-Item -LiteralPath $target.FullName -Force
    }
    Write-Host "Arquivos runtime removidos: $($targets.Count)."
}

function Invoke-Tests {
    $python = Get-ProjectPython
    & $python -m pytest -q
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

function Invoke-Checks {
    $python = Get-ProjectPython
    & $python -m ruff check app tests
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $python -m mypy app tests
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $python -m pytest -q
}

switch ($Command) {
    "run" { Start-App -Reload:$Dev -AsBackground:$Background }
    "stop" { Stop-Stack }
    "restart" {
        Stop-Stack
        Start-App -Reload:$Dev -AsBackground:$Background
    }
    "tools" {
        switch ($Tool) {
            "status" { Show-Status }
            "logs" { Show-Logs }
            "migrate" { Invoke-Migrations }
            "test" { Invoke-Tests }
            "check" { Invoke-Checks }
            "clean" { Clean-Runtime }
            default { throw "Informe uma ferramenta: status, logs, test, check, migrate ou clean." }
        }
    }
}
