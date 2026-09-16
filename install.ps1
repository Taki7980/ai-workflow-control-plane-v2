param(
    [string]$Version = "",
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA "Programs\AIWorkflow")
)

$ErrorActionPreference = "Stop"
$Repo = "Taki7980/ai-workflow-control-plane-v2"

if ([string]::IsNullOrWhiteSpace($Version)) {
    $Headers = @{
        "Accept" = "application/vnd.github+json"
        "User-Agent" = "ai-workflow-installer"
    }
    $Release = Invoke-RestMethod "https://api.github.com/repos/$Repo/releases/latest" -Headers $Headers
    $Tag = [string]$Release.tag_name
    if ($Tag -notmatch '^v(?<Version>[0-9]+\.[0-9]+\.[0-9]+)$') {
        throw "Unable to resolve a stable AI Workflow release from releases/latest"
    }
    $Version = $Matches.Version
}

if ($Version -notmatch '^[0-9]+\.[0-9]+\.[0-9]+$') {
    throw "Invalid AI Workflow release version: $Version"
}

$Asset = "ai-workflow-v$Version-windows-x86_64.exe"
$Base = "https://github.com/$Repo/releases/download/v$Version"
if ($env:AI_WORKFLOW_TEST_RELEASE_BASE) {
    $TestBase = [Uri]$env:AI_WORKFLOW_TEST_RELEASE_BASE
    if ($TestBase.Scheme -ne "http" -or $TestBase.Host -notin @("127.0.0.1", "localhost")) {
        throw "AI_WORKFLOW_TEST_RELEASE_BASE is restricted to localhost HTTP"
    }
    $Base = $env:AI_WORKFLOW_TEST_RELEASE_BASE.TrimEnd("/")
}

$Temp = Join-Path $env:TEMP "ai-workflow-$Version-$PID"
New-Item -ItemType Directory -Force -Path $Temp | Out-Null

try {
    $Binary = Join-Path $Temp $Asset
    $Checksums = Join-Path $Temp "SHA256SUMS"
    Invoke-WebRequest "$Base/$Asset" -OutFile $Binary
    Invoke-WebRequest "$Base/SHA256SUMS" -OutFile $Checksums

    $Line = Get-Content $Checksums | Where-Object { $_ -match "\s$([regex]::Escape($Asset))$" } | Select-Object -First 1
    if (-not $Line) { throw "No SHA256 checksum found for $Asset" }
    $Expected = ($Line -split "\s+")[0].ToLowerInvariant()
    $Actual = (Get-FileHash $Binary -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($Expected -ne $Actual) { throw "SHA256 verification failed" }

    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
    $Target = Join-Path $InstallDir "ai-workflow.exe"
    Copy-Item $Binary $Target -Force

    $UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $Entries = @($UserPath -split ";" | Where-Object { $_ })
    if ($Entries -notcontains $InstallDir) {
        $NewPath = (@($Entries) + $InstallDir) -join ";"
        [Environment]::SetEnvironmentVariable("Path", $NewPath, "User")
    }

    Write-Host "Installed AI Workflow $Version to $Target"
    Write-Host "SHA-256 verified."
    Write-Host "Build provenance:"
    Write-Host "  gh attestation verify `"$Target`" --repo $Repo"
} finally {
    Remove-Item -Recurse -Force $Temp -ErrorAction SilentlyContinue
}
