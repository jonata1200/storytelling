[CmdletBinding()]
param(
    [int]$Port = 8000,
    [int]$PortRangeEnd = 8020,
    [switch]$KeepDocker,
    [switch]$Down
)

& "$PSScriptRoot\app.ps1" `
    stop `
    -Port $Port `
    -PortRangeEnd $PortRangeEnd `
    -KeepDocker:$KeepDocker `
    -Down:$Down
