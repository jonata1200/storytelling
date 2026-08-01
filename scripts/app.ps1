[CmdletBinding()]
param(
    [ValidateSet("up", "dev", "start", "stop", "down", "restart", "status", "logs", "test", "check", "migrate", "clean")]
    [string]$Command = "up",
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 8000,
    [int]$PortRangeEnd = 8020,
    [Alias("SkipDocker")]
    [switch]$NoDocker,
    [Alias("SkipMigrations")]
    [switch]$NoMigrate,
    [switch]$Foreground,
    [switch]$Background,
    [switch]$KeepDocker,
    [switch]$Follow
)

$ErrorActionPreference = "Stop"

$story = Join-Path $PSScriptRoot "story.ps1"
$storyOptions = @{
    HostAddress = $HostAddress
    Port = $Port
    PortRangeEnd = $PortRangeEnd
}

if ($NoDocker) { $storyOptions.NoDocker = $true }
if ($NoMigrate) { $storyOptions.NoMigrate = $true }

switch ($Command) {
    "up" {
        $storyOptions.Command = "run"
        if ($Background) { $storyOptions.Background = $true }
    }
    "start" {
        $storyOptions.Command = "run"
        if (-not $Foreground) { $storyOptions.Background = $true }
    }
    "dev" {
        $storyOptions.Command = "run"
        $storyOptions.Dev = $true
    }
    "stop" {
        $storyOptions.Command = "stop"
        $storyOptions.KeepDocker = $true
    }
    "down" {
        $storyOptions.Command = "stop"
        if ($KeepDocker) { $storyOptions.KeepDocker = $true }
    }
    "restart" {
        $storyOptions.Command = "restart"
        if ($Background) { $storyOptions.Background = $true }
        if ($KeepDocker) { $storyOptions.KeepDocker = $true }
    }
    "status" {
        $storyOptions.Command = "tools"
        $storyOptions.Tool = "status"
    }
    "logs" {
        $storyOptions.Command = "tools"
        $storyOptions.Tool = "logs"
        if ($Follow) { $storyOptions.Follow = $true }
    }
    "migrate" {
        $storyOptions.Command = "tools"
        $storyOptions.Tool = "migrate"
    }
    "test" {
        $storyOptions.Command = "tools"
        $storyOptions.Tool = "test"
    }
    "check" {
        $storyOptions.Command = "tools"
        $storyOptions.Tool = "check"
    }
    "clean" {
        $storyOptions.Command = "tools"
        $storyOptions.Tool = "clean"
    }
}

& $story @storyOptions
