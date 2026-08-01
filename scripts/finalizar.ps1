[CmdletBinding()]
param(
    [int]$Port = 8000,
    [int]$PortRangeEnd = 8020,
    [switch]$KeepDocker,
    [switch]$Down
)

$storyOptions = @{
    Command = "stop"
    Port = $Port
    PortRangeEnd = $PortRangeEnd
}
if ($KeepDocker) { $storyOptions.KeepDocker = $true }

& "$PSScriptRoot\story.ps1" @storyOptions
