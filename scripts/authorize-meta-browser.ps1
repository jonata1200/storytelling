param(
    [ValidateSet("image", "vibes")]
    [string]$Target = "image",
    [string]$ProfilePath = ""
)

$repoRoot = Split-Path -Parent $PSScriptRoot
if (-not $ProfilePath) {
    $profileName = if ($Target -eq "vibes") { "vibes" } else { "meta" }
    $ProfilePath = Join-Path $repoRoot "runtime\browser_profiles\$profileName"
}

$destinationUrl = if ($Target -eq "vibes") { "https://vibes.ai/" } else { "https://www.meta.ai/" }
$fullProfilePath = [System.IO.Path]::GetFullPath($ProfilePath)
$chromeCandidates = @(
    (Join-Path $env:ProgramFiles "Google\Chrome\Application\chrome.exe"),
    (Join-Path ${env:ProgramFiles(x86)} "Google\Chrome\Application\chrome.exe"),
    (Join-Path $env:LOCALAPPDATA "Google\Chrome\Application\chrome.exe")
)
$chrome = $chromeCandidates |
    Where-Object { $_ -and (Test-Path -LiteralPath $_) } |
    Select-Object -First 1

if (-not $chrome) {
    Write-Error "Google Chrome nao encontrado. Instale o Chrome para autorizar o perfil."
    Read-Host "Pressione Enter para fechar"
    exit 1
}

New-Item -ItemType Directory -Force -Path $fullProfilePath | Out-Null
Write-Host "Uma janela normal do Chrome sera aberta em $destinationUrl."
Write-Host "Conclua o login e feche essa janela para liberar o perfil para a aplicacao."
$chromeProcess = Start-Process `
    -FilePath $chrome `
    -ArgumentList @(
        "--user-data-dir=$fullProfilePath",
        "--no-first-run",
        "--no-default-browser-check",
        "--new-window",
        $destinationUrl
    ) `
    -PassThru
$chromeProcess.WaitForExit()
Write-Host "Janela de autorizacao encerrada. O perfil foi liberado para a aplicacao."
Start-Sleep -Seconds 1
