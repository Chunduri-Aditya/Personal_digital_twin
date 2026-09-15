# Delete the twin's derived and personal data (docs/PLAN_UNIFIED.md 3.6): profile, transcripts, redaction report,
# indexes, chunks, digest, reflections, eval results, audit, telemetry, probes, item answers and scores.
# Example files (*.example*.md / *.example*.json) and the item bank (bank.json) are never removed.
#
#   powershell -ExecutionPolicy Bypass -File scripts\delete_twin.ps1              # dry run: lists, removes nothing
#   powershell -ExecutionPolicy Bypass -File scripts\delete_twin.ps1 -Confirm     # removes the listed files
#   ... -DataDir data_test                                                        # another data folder
#
# A relative -DataDir resolves against the project root (the parent of this scripts folder), the default being
# "data". After -Confirm the app opens on Onboarding because data\twin_profile.md is gone.
param(
    [switch]$Confirm,
    [string]$DataDir = "data"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
if ([System.IO.Path]::IsPathRooted($DataDir)) { $dataPath = $DataDir } else { $dataPath = Join-Path $projectRoot $DataDir }
if (-not (Test-Path -LiteralPath $dataPath -PathType Container)) {
    Write-Host "delete_twin: data dir not found: $dataPath"
    exit 1
}
$dataPath = (Resolve-Path -LiteralPath $dataPath).Path

# Relative to $DataDir. Keep in sync with docs/CONTRACTS.md (scripts/delete_twin.ps1).
$targets = @(
    "twin_profile.md",
    "interview_transcript.md",
    "interview_transcript.redacted.md",
    "redaction_report.json",
    "index_nomic.npz",
    "index_gemma.npz",
    "index_lms_nomic.npz",
    "chunks.json",
    "digest.md",
    "reflections.md",
    "eval_results.json",
    "audit.jsonl",
    "telemetry.jsonl",
    "probes.json",
    "items\self_answers.json",
    "items\self_answers_retest.json",
    "items\twin_answers.json",
    "items\scores.json"
)

$mode = if ($Confirm) { "CONFIRMED: removing" } else { "dry run: nothing is removed (add -Confirm)" }
Write-Host "delete_twin: data dir $dataPath ($mode)"

$present = @()
$absent = @()
foreach ($rel in $targets) {
    # Defensive: the list above never names an example file or the bank; refuse them even if it did.
    $leaf = Split-Path -Leaf $rel
    if ($leaf -like "*.example*" -or $leaf -ieq "bank.json") { continue }
    $full = Join-Path $dataPath $rel
    if (Test-Path -LiteralPath $full -PathType Leaf) {
        $present += $full
        $size = (Get-Item -LiteralPath $full).Length
        if ($Confirm) { Write-Host ("  removing  {0}  ({1} bytes)" -f $rel, $size) }
        else { Write-Host ("  would remove  {0}  ({1} bytes)" -f $rel, $size) }
    } else {
        $absent += $rel
    }
}
if ($absent.Count -gt 0) { Write-Host ("  absent: " + ($absent -join ", ")) }

$kept = @(Get-ChildItem -LiteralPath $dataPath -Recurse -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -like "*.example*" -or $_.Name -ieq "bank.json" } |
    ForEach-Object { $_.FullName.Substring($dataPath.Length).TrimStart("\") })
Write-Host ("example files kept (never removed): " + $(if ($kept.Count -gt 0) { $kept -join ", " } else { "none found" }))

if (-not $Confirm) {
    Write-Host ("dry run: {0} file(s) would be removed; re-run with -Confirm to delete them" -f $present.Count)
    exit 0
}

$removed = 0
foreach ($full in $present) {
    Remove-Item -LiteralPath $full -Force -Confirm:$false
    $removed += 1
}
Write-Host ("removed {0} files" -f $removed)
Write-Host "the app now opens on Onboarding (no data\twin_profile.md)"
exit 0
