[CmdletBinding()]
param(
    [ValidateSet("start", "stop", "restart")]
    [string]$Action = "start",
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 8000,
    [int]$PortRangeEnd = 8020,
    [switch]$SkipDocker,
    [switch]$SkipMigrations,
    [switch]$SkipWorker,
    [switch]$Background,
    [switch]$KeepDocker,
    [switch]$Down
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

function Test-StorytellingPort {
    param([int]$CandidatePort)

    try {
        $health = Invoke-RestMethod `
            -Uri "http://127.0.0.1:$CandidatePort/api/v1/health/live" `
            -TimeoutSec 2 `
            -ErrorAction Stop
        return ([string]$health.app -like "Storytelling*")
    } catch {
        return $false
    }
}

function Stop-ProcessSafely {
    param(
        [int]$ProcessId,
        [string]$Description
    )

    $process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if ($null -ne $process) {
        try {
            Write-Host "Finalizando $Description (PID $ProcessId)..."
            Stop-Process -Id $ProcessId -Force -ErrorAction Stop
            return $true
        } catch {
            Write-Warning "O processo PID $ProcessId exige permissao de administrador."
        }
    }

    Write-Host "Solicitando permissao do Windows para finalizar o PID $ProcessId..."
    try {
        $elevatedKill = Start-Process `
            -FilePath "$env:SystemRoot\System32\taskkill.exe" `
            -ArgumentList @("/PID", $ProcessId.ToString(), "/T", "/F") `
            -Verb RunAs `
            -Wait `
            -PassThru
        return ($elevatedKill.ExitCode -eq 0)
    } catch {
        Write-Warning "A autorizacao para finalizar o PID $ProcessId foi cancelada ou negada."
        return $false
    }
}

function Test-CeleryWorkerProcess {
    param([int]$ProcessId)

    $process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if ($null -eq $process -or $process.ProcessName -notmatch "python|celery") {
        return $false
    }

    try {
        $workerProcess = Get-CimInstance `
            -ClassName Win32_Process `
            -Filter "ProcessId = $ProcessId" `
            -ErrorAction Stop
        $commandLine = [string]$workerProcess.CommandLine
        return (
            $commandLine -match "celery" -and
            $commandLine -match "app\.workers\.celery_app\.celery_app"
        )
    } catch {
        return $true
    }
}

function Stop-AppProcesses {
    $runtimeDir = Join-Path $ProjectRoot ".runtime"
    $stoppedIds = [System.Collections.Generic.HashSet[int]]::new()
    $stoppedPorts = [System.Collections.Generic.HashSet[int]]::new()

    if (Test-Path $runtimeDir) {
        $workerPidFiles = Get-ChildItem `
            -Path $runtimeDir `
            -Filter "celery-worker*.pid" `
            -File `
            -ErrorAction SilentlyContinue
        foreach ($pidFile in $workerPidFiles) {
            $pidValue = Get-Content $pidFile.FullName -ErrorAction SilentlyContinue |
                Select-Object -First 1
            if ($pidValue -match "^\d+$") {
                $numericPid = [int]$pidValue
                if (Test-CeleryWorkerProcess -ProcessId $numericPid) {
                    if (Stop-ProcessSafely `
                        -ProcessId $numericPid `
                        -Description "worker Celery registrado do Storytelling") {
                        [void]$stoppedIds.Add($numericPid)
                    }
                }
            }
            Remove-Item -LiteralPath $pidFile.FullName -Force -ErrorAction SilentlyContinue
        }

        $pidFiles = Get-ChildItem `
            -Path $runtimeDir `
            -Filter "uvicorn*.pid" `
            -File `
            -ErrorAction SilentlyContinue
        foreach ($pidFile in $pidFiles) {
            $pidValue = Get-Content $pidFile.FullName -ErrorAction SilentlyContinue |
                Select-Object -First 1
            if ($pidValue -match "^\d+$") {
                $numericPid = [int]$pidValue
                $registeredPort = $null
                if ($pidFile.BaseName -match "^uvicorn-(\d+)$") {
                    $registeredPort = [int]$Matches[1]
                }
                $registeredProcess = Get-Process `
                    -Id $numericPid `
                    -ErrorAction SilentlyContinue
                $isExpectedProcess = (
                    $null -ne $registeredProcess -and
                    $registeredProcess.ProcessName -match "python|uvicorn"
                )
                $isConfirmedApp = (
                    $null -ne $registeredPort -and
                    (Test-StorytellingPort -CandidatePort $registeredPort)
                )
                if ($isExpectedProcess -and $isConfirmedApp) {
                    if (Stop-ProcessSafely `
                        -ProcessId $numericPid `
                        -Description "instancia registrada do Storytelling") {
                        [void]$stoppedIds.Add($numericPid)
                        [void]$stoppedPorts.Add($registeredPort)
                    }
                }
            }
            Remove-Item -LiteralPath $pidFile.FullName -Force -ErrorAction SilentlyContinue
        }
    }

    $lastPort = [Math]::Max($Port, $PortRangeEnd)
    foreach ($candidatePort in $Port..$lastPort) {
        $connections = Get-NetTCPConnection `
            -LocalPort $candidatePort `
            -State Listen `
            -ErrorAction SilentlyContinue
        if ($null -eq $connections) {
            continue
        }
        if (-not (Test-StorytellingPort -CandidatePort $candidatePort)) {
            Write-Warning "Porta $candidatePort ocupada por outro servico; ela foi preservada."
            continue
        }
        $processIds = $connections | Select-Object -ExpandProperty OwningProcess -Unique
        foreach ($processId in $processIds) {
            if ($stoppedIds.Contains([int]$processId)) {
                continue
            }
            if (Stop-ProcessSafely `
                -ProcessId ([int]$processId) `
                -Description "Storytelling na porta $candidatePort") {
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

function Start-CeleryWorker {
    param([string]$PythonExecutable)

    if ($SkipWorker) {
        Write-Host "Worker Celery nao iniciado por causa de -SkipWorker."
        return
    }

    $runtimeDir = Join-Path $ProjectRoot ".runtime"
    New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
    $pidFile = Join-Path $runtimeDir "celery-worker.pid"
    $stdoutLog = Join-Path $runtimeDir "celery-worker.out.log"
    $stderrLog = Join-Path $runtimeDir "celery-worker.err.log"

    if (Test-Path $pidFile) {
        $pidValue = Get-Content $pidFile -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($pidValue -match "^\d+$") {
            if (Test-CeleryWorkerProcess -ProcessId ([int]$pidValue)) {
                Write-Host "Worker Celery ja esta em execucao (PID $pidValue)."
                return
            }
        }
        Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
    }

    $workerArguments = @(
        "-m",
        "celery",
        "-A",
        "app.workers.celery_app.celery_app",
        "worker",
        "--loglevel=info",
        "--pool=solo",
        "--queues",
        "storytelling"
    )

    $process = Start-Process `
        -FilePath $PythonExecutable `
        -ArgumentList $workerArguments `
        -WorkingDirectory $ProjectRoot `
        -RedirectStandardOutput $stdoutLog `
        -RedirectStandardError $stderrLog `
        -PassThru `
        -WindowStyle Hidden

    Set-Content -Path $pidFile -Value $process.Id
    Write-Host "Worker Celery iniciado em segundo plano."
    Write-Host "Worker PID: $($process.Id)"
    Write-Host "Worker logs: $stdoutLog e $stderrLog"
}

function Stop-Storytelling {
    Stop-AppProcesses

    if ($KeepDocker) {
        Write-Host "Containers mantidos em execucao por causa de -KeepDocker."
        return
    }

    $docker = Get-DockerExecutable
    if ($null -eq $docker) {
        Write-Warning "Docker nao encontrado. A aplicacao foi finalizada, mas os containers nao foram alterados."
        return
    }

    if ($Down) {
        Write-Host "Executando docker compose down..."
        & $docker compose down
    } else {
        Write-Host "Parando containers com docker compose stop..."
        & $docker compose stop
    }

    Write-Host "Projeto finalizado."
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

function Start-Storytelling {
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
        if (Test-StorytellingPort -CandidatePort $Port) {
            Stop-AppProcesses
        } else {
            $requestedPort = $Port
            $Port = Get-NextAvailablePort -StartPort ($requestedPort + 1)
            Write-Warning "Porta $requestedPort ocupada por outro servico; usando porta $Port."
        }
    }

    Start-CeleryWorker -PythonExecutable $python

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
        return
    }

    $uvicornArguments += "--reload"
    Write-Host "Iniciando aplicacao em primeiro plano: $url"
    Write-Host "Para finalizar, pressione Ctrl+C ou execute: .\scripts\app.ps1 stop"
    & $python @uvicornArguments
}

switch ($Action) {
    "start" { Start-Storytelling }
    "stop" { Stop-Storytelling }
    "restart" {
        Stop-Storytelling
        Start-Storytelling
    }
}
