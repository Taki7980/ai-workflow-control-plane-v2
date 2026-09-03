param([Parameter(Mandatory=$true)][string]$Query,[int]$MaxResults=5)
& (Join-Path $PSScriptRoot '_invoke.ps1') memory search $Query --limit $MaxResults
