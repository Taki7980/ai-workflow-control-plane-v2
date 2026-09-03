param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Args)
$workspace = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
Push-Location $workspace
try {
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) { & python -m ai_workflow @Args; exit $LASTEXITCODE }
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) { & py -3 -m ai_workflow @Args; exit $LASTEXITCODE }
    throw 'Python 3.10+ was not found on PATH.'
} finally { Pop-Location }
