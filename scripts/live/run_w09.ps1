[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Home,

    [Parameter(Mandatory = $true)]
    [string]$SmallUsername,

    [string]$VolumeUsername = "",
    [string]$SmallStart = "2026-07-01T00:00:00Z",
    [string]$SmallCutoff = "2026-07-08T00:00:00Z",
    [string]$ResumeStart = "2026-01-01T00:00:00Z",
    [string]$ResumeCutoff = "2026-07-01T00:00:00Z",
    [string]$VolumeStart = "2024-01-01T00:00:00Z",
    [string]$VolumeCutoff = "2026-07-01T00:00:00Z",
    [int]$InitialWindowDays = 30,
    [int]$MinWindowSeconds = 3600,
    [int]$MaxPostsPerWindow = 5000,
    [int]$TimelineLimit = -1,
    [switch]$AllowProxyEnvironment,
    [switch]$DoNotPromptForCookie
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
if (Get-Variable -Name PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue) {
    $PSNativeCommandUseErrorActionPreference = $false
}

if ($env:CI -or $env:GITHUB_ACTIONS) {
    throw "W09 authenticated live E2E is forbidden in CI."
}

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $RepoRoot
$ResolvedHome = [System.IO.Path]::GetFullPath($Home)
$VolumeUsername = if ([string]::IsNullOrWhiteSpace($VolumeUsername)) {
    $SmallUsername
} else {
    $VolumeUsername
}

$env:X_SCRAP_HOME = $ResolvedHome
$env:TWS_TELEMETRY = "0"
$env:DO_NOT_TRACK = "1"

$ProxyNames = @(
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
    "http_proxy", "https_proxy", "all_proxy"
) | Where-Object { [Environment]::GetEnvironmentVariable($_) }
if ($ProxyNames.Count -gt 0 -and -not $AllowProxyEnvironment) {
    throw "Proxy environment detected: $($ProxyNames -join ', '). Clear it or pass -AllowProxyEnvironment explicitly."
}

function Invoke-PythonCase {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [int[]]$ExpectedExitCodes = @(0)
    )

    & python @Arguments
    $Code = $LASTEXITCODE
    if ($ExpectedExitCodes -notcontains $Code) {
        throw "Command failed with exit code $Code: python $($Arguments -join ' ')"
    }
    return $Code
}

function Get-ActiveAccounts {
    $Raw = & python scripts/live/run_user_export_smoke.py --home $ResolvedHome --preflight-only | Out-String
    if ($LASTEXITCODE -ne 0) {
        throw "Local account preflight failed."
    }
    $Accounts = $Raw | ConvertFrom-Json
    return @($Accounts | Where-Object { $_.active -eq $true })
}

Write-Host "[W09] Repository: $RepoRoot"
Write-Host "[W09] Private state: $ResolvedHome"
Write-Host "[W09] Running deterministic local preflight..."
Invoke-PythonCase -Arguments @("-m", "compileall", "-q", "src", "tests", "scripts")
Invoke-PythonCase -Arguments @("-m", "pytest", "-q")

$ActiveAccounts = Get-ActiveAccounts
if ($ActiveAccounts.Count -eq 0) {
    if ($DoNotPromptForCookie) {
        throw "No active local X session. Run x-scrap auth add-cookie --label primary."
    }
    Write-Host "[W09] No active account. Enter your own browser Cookie in the no-echo prompt."
    & x-scrap --home $ResolvedHome auth add-cookie --label primary
    if ($LASTEXITCODE -ne 0) {
        throw "Cookie import failed."
    }
    $ActiveAccounts = Get-ActiveAccounts
}
if ($ActiveAccounts.Count -ne 1) {
    throw "W09 requires exactly one active local account; found $($ActiveAccounts.Count)."
}

$EvidenceDir = Join-Path $ResolvedHome "live-evidence"
New-Item -ItemType Directory -Force -Path $EvidenceDir | Out-Null
$ProxyArgument = @()
if ($AllowProxyEnvironment) {
    $ProxyArgument = @("--allow-proxy-environment")
}
$CommonTuning = @(
    "--home", $ResolvedHome,
    "--initial-window-days", "$InitialWindowDays",
    "--min-window-seconds", "$MinWindowSeconds",
    "--max-posts-per-window", "$MaxPostsPerWindow",
    "--timeline-limit", "$TimelineLimit",
    "--acknowledge-live-x"
) + $ProxyArgument

Write-Host "[W09] Case 1/4: small fixed range"
Invoke-PythonCase -Arguments (@(
    "scripts/live/run_e2e_case.py",
    "--case-name", "small-fixed-range",
    "--username", $SmallUsername,
    "--start", $SmallStart,
    "--cutoff", $SmallCutoff
) + $CommonTuning)

Write-Host "[W09] Case 2/4: controlled interruption after one committed page"
Invoke-PythonCase -Arguments (@(
    "scripts/live/run_e2e_case.py",
    "--case-name", "interruption-resume",
    "--username", $VolumeUsername,
    "--start", $ResumeStart,
    "--cutoff", $ResumeCutoff,
    "--interrupt-after-pages", "1"
) + $CommonTuning) -ExpectedExitCodes @(130)

$Checkpoint = Join-Path $EvidenceDir "interruption-resume.json"
Write-Host "[W09] Case 3/4: resume from the committed checkpoint"
Invoke-PythonCase -Arguments (@(
    "scripts/live/run_e2e_case.py",
    "--case-name", "interruption-resume-final",
    "--username", $VolumeUsername,
    "--start", $ResumeStart,
    "--cutoff", $ResumeCutoff,
    "--resume-from-report", $Checkpoint
) + $CommonTuning)

Write-Host "[W09] Case 4/4: higher-volume historical range"
Invoke-PythonCase -Arguments (@(
    "scripts/live/run_e2e_case.py",
    "--case-name", "higher-volume",
    "--username", $VolumeUsername,
    "--start", $VolumeStart,
    "--cutoff", $VolumeCutoff
) + $CommonTuning)

$Reports = @(
    (Join-Path $EvidenceDir "small-fixed-range.json"),
    $Checkpoint,
    (Join-Path $EvidenceDir "interruption-resume-final.json"),
    (Join-Path $EvidenceDir "higher-volume.json")
)
$Acceptance = Join-Path $EvidenceDir "W09_ACCEPTANCE.json"
Write-Host "[W09] Verifying the four sanitized reports and cross-case resume contract"
Invoke-PythonCase -Arguments (@(
    "scripts/live/validate_e2e_report.py",
    "--acceptance-output", $Acceptance
) + $Reports)

Write-Host "[W09] PASS"
Write-Host "[W09] Sanitized acceptance evidence: $Acceptance"
Get-Content -LiteralPath $Acceptance
