[CmdletBinding()]
param(
    [int]$Port = 8000,
    [int]$PortRangeEnd = 8020,
    [switch]$KeepDocker,
    [switch]$Down
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $ProjectRoot

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

function Stop-AllAppProcesses {
    $runtimeDir = Join-Path $ProjectRoot ".runtime"
    $stoppedIds = [System.Collections.Generic.HashSet[int]]::new()
    $stoppedPorts = [System.Collections.Generic.HashSet[int]]::new()

    if (Test-Path $runtimeDir) {
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
            } else {
                Write-Warning (
                    "A instancia Storytelling na porta $candidatePort foi encontrada, " +
                    "mas o PID $processId nao pode ser acessado por esta sessao."
                )
            }
        }
    }

    Write-Host (
        "Instancias finalizadas: $($stoppedIds.Count). " +
        "Portas liberadas: $(if ($stoppedPorts.Count) { $stoppedPorts -join ', ' } else { 'nenhuma' })."
    )
}

Stop-AllAppProcesses

if ($KeepDocker) {
    Write-Host "Containers mantidos em execucao por causa de -KeepDocker."
    exit 0
}

$docker = Get-DockerExecutable
if ($null -eq $docker) {
    Write-Warning "Docker nao encontrado. A aplicacao foi finalizada, mas os containers nao foram alterados."
    exit 0
}

if ($Down) {
    Write-Host "Executando docker compose down..."
    & $docker compose down
} else {
    Write-Host "Parando containers com docker compose stop..."
    & $docker compose stop
}

Write-Host "Projeto finalizado."
