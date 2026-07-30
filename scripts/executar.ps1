[CmdletBinding()]
param(
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 8000,
    [Alias("SkipDocker")]
    [switch]$NoDocker,
    [Alias("SkipMigrations")]
    [switch]$NoMigrate,
    [switch]$Background,
    [switch]$Dev
)

$command = if ($Dev) { "dev" } else { "up" }

& "$PSScriptRoot\app.ps1" `
    $command `
    -HostAddress $HostAddress `
    -Port $Port `
    -NoDocker:$NoDocker `
    -NoMigrate:$NoMigrate
