param([switch]$Incremental)
& (Join-Path $PSScriptRoot '_invoke.ps1') index
