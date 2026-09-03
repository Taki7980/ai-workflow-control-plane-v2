param([Parameter(Mandatory=$true)][string]$Type,[Parameter(Mandatory=$true)][string]$Keywords,[Parameter(Mandatory=$true)][string]$Problem,[Parameter(Mandatory=$true)][string]$Solution,[string]$Lesson='',[string]$FilesChanged='')
$summary = if($Lesson){$Lesson}else{$Solution}; $args=@('memory','add','--type',$Type,'--keywords',$Keywords,'--summary',$summary,'--evidence',("Problem: $Problem; Solution: $Solution"));
foreach($f in ($FilesChanged -split ',' | Where-Object { $_.Trim() })){ $args += @('--file',$f.Trim()) }
& (Join-Path $PSScriptRoot '_invoke.ps1') @args
