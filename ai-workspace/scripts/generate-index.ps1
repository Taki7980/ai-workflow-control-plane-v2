param([switch]$Incremental)
$indexArgs = @('index')
if ($Incremental) { $indexArgs += '--incremental' }
& (Join-Path $PSScriptRoot '_invoke.ps1') @indexArgs
