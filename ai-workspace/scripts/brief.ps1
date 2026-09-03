param([string]$Role='builder',[Parameter(Mandatory=$true)][string]$Query,[string]$Symbol='',[string]$Endpoint='')
$args=@('brief',$Query); if($Symbol){$args+=@('--symbol',$Symbol)}; if($Endpoint){$args+=@('--endpoint',$Endpoint)}
& (Join-Path $PSScriptRoot '_invoke.ps1') @args
