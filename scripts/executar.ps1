[CmdletBinding()]
param(
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 8000,
    [switch]$SkipDocker,
    [switch]$SkipMigrations,
    [switch]$Background
)

& "$PSScriptRoot\app.ps1" `
    start `
    -HostAddress $HostAddress `
    -Port $Port `
    -SkipDocker:$SkipDocker `
    -SkipMigrations:$SkipMigrations `
    -Background:$Background
