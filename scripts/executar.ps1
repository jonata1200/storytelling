$ErrorActionPreference = "Stop"

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

$storyOptions = @{
    Command = "run"
    HostAddress = $HostAddress
    Port = $Port
}
if ($Dev) { $storyOptions.Dev = $true }
if ($Background) { $storyOptions.Background = $true }
if ($NoDocker) { $storyOptions.NoDocker = $true }
if ($NoMigrate) { $storyOptions.NoMigrate = $true }

& "$PSScriptRoot\story.ps1" @storyOptions
