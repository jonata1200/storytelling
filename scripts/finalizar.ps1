[CmdletBinding()]
param(
    [int]$Port = 8000,
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

function Stop-AppProcess {
    $runtimeDir = Join-Path $ProjectRoot ".runtime"
    $pidFile = Join-Path $runtimeDir "uvicorn.pid"
    $stopped = $false

    if (Test-Path $pidFile) {
        $pidValue = Get-Content $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($pidValue -match "^\d+$") {
            $process = Get-Process -Id ([int]$pidValue) -ErrorAction SilentlyContinue
            if ($null -ne $process) {
                Write-Host "Finalizando aplicacao pelo PID $pidValue..."
                Stop-Process -Id ([int]$pidValue) -Force
                $stopped = $true
            }
        }
        Remove-Item -Path $pidFile -Force -ErrorAction SilentlyContinue
    }

    if (-not $stopped) {
        $connections = Get-NetTCPConnection `
            -LocalPort $Port `
            -State Listen `
            -ErrorAction SilentlyContinue

        $processIds = $connections |
            Select-Object -ExpandProperty OwningProcess -Unique

        foreach ($processId in $processIds) {
            $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
            if ($null -eq $process) {
                continue
            }
            if ($process.ProcessName -match "python|uvicorn") {
                Write-Host "Finalizando processo $($process.ProcessName) na porta $Port..."
                Stop-Process -Id $processId -Force
                $stopped = $true
            }
        }
    }

    if (-not $stopped) {
        Write-Host "Nenhum processo da aplicacao encontrado na porta $Port."
    }
}

Stop-AppProcess

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
