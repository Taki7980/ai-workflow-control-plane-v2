param(
    [string]$Version = "2.3.0",
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA "Programs\AIWorkflow")
)

$ErrorActionPreference = "Stop"
$Repo = "Taki7980/ai-workflow-control-plane-v2"
$Asset = "ai-workflow-v$Version-windows-x86_64.exe"
$Base = "https://github.com/$Repo/releases/download/v$Version"
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
    Write-Host "Installed $Target"
} finally {
    Remove-Item -Recurse -Force $Temp -ErrorAction SilentlyContinue
}
