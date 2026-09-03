param([switch]$Fix)
if($Fix){ Get-Content (Join-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) 'ai-workspace/templates/handoff-template.md'); exit 0 }
& (Join-Path $PSScriptRoot '_invoke.ps1') handoff validate
