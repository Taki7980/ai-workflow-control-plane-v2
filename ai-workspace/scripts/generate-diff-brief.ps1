param([Parameter(Mandatory=$true)][string]$ProjectName)
Write-Warning 'generate-diff-brief.ps1 previously contained bootstrap logic. It is retained only as a compatibility alias to setup.ps1.'
& (Join-Path $PSScriptRoot 'setup.ps1') -ProjectName $ProjectName
