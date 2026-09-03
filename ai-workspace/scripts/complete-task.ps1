param([switch]$ValidateOnly,[string]$Type='verified-fix',[string]$Keywords='',[string]$Problem='',[string]$Solution='',[string]$Lesson='',[string]$FilesChanged='')
& (Join-Path $PSScriptRoot '_invoke.ps1') handoff validate
if($LASTEXITCODE -ne 0){ exit $LASTEXITCODE }
if($ValidateOnly){ 'completion_check: PASS'; exit 0 }
if($Keywords -and ($Solution -or $Lesson)){
  $summary=if($Lesson){$Lesson}else{$Solution}; $args=@('memory','add','--type',$Type,'--keywords',$Keywords,'--summary',$summary,'--evidence',("Problem: $Problem; Solution: $Solution"));
  foreach($f in ($FilesChanged -split ',' | Where-Object { $_.Trim() })){ $args+=@('--file',$f.Trim()) }
  & (Join-Path $PSScriptRoot '_invoke.ps1') @args
}
& (Join-Path $PSScriptRoot '_invoke.ps1') index
