param([Parameter(Mandatory=$true)][string]$ProjectName)
& (Join-Path $PSScriptRoot '_invoke.ps1') init --project-name $ProjectName
