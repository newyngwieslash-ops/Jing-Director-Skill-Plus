param(
    [ValidateSet("codex", "zcode", "claude", "both")]
    [string]$Agent = "both",
    [string]$TargetRoot = "",
    [switch]$Upgrade,
    [switch]$DryRun,
    [switch]$VerifyPackage
)
$ErrorActionPreference = "Stop"
$tool = Join-Path $PSScriptRoot "scripts/install_skill.py"
$launcher = Get-Command py -ErrorAction SilentlyContinue
$python = Get-Command python -ErrorAction SilentlyContinue
$toolArgs = @($tool, "--agent", $Agent)
if ($TargetRoot) { $toolArgs += @("--target-root", $TargetRoot) }
if ($Upgrade) { $toolArgs += "--upgrade" }
if ($DryRun) { $toolArgs += "--dry-run" }
if ($VerifyPackage) { $toolArgs += "--verify-package" }
if ($launcher) {
    & $launcher.Source -3 @toolArgs
} elseif ($python) {
    & $python.Source @toolArgs
} else {
    throw "Python 3.10+ is required. Copy the complete jingstudio folder manually, or install Python first. Older skills must remain unchanged."
}
exit $LASTEXITCODE
