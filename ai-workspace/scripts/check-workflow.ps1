param([switch]$AllowProductSourceMutation)
& (Join-Path $PSScriptRoot '_invoke.ps1') doctor --strict
