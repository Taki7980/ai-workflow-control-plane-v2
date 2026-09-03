param([string]$Symbol='',[string]$Endpoint='',[string]$Err='',[string]$Module='',[string]$Brain='',[string]$Caller='',[switch]$DebugIndex)
$query = @($Symbol,$Endpoint,$Err,$Module,$Brain,$Caller) | Where-Object { $_ } | Select-Object -First 1
if(-not $query){ throw 'Provide Symbol, Endpoint, Err, Module, Brain, or Caller' }
$args=@('context',$query); if($Symbol){$args+=@('--symbol',$Symbol)}; if($Endpoint){$args+=@('--endpoint',$Endpoint)}
& (Join-Path $PSScriptRoot '_invoke.ps1') @args
