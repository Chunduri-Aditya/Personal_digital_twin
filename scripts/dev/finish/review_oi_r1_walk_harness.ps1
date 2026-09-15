# Review r1 of lane onboarding_items (no GPU, no model): boots scripts\dev\finish\review_oi_r1_walk_app.py (a
# model-free page with a plain and a lane-styled gr.Walkthrough) on a UI port, runs review_oi_r1_walk_probe.py, and
# ALWAYS stops the app it started, all inside this one command (the ui_check.ps1 boot and stop discipline).
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\dev\finish\review_oi_r1_walk_harness.ps1 -Port 7876 -OutDir <dir>
param(
    [Parameter(Mandatory = $true)][int]$Port,
    [Parameter(Mandatory = $true)][string]$OutDir,
    [int]$Selected = 1,
    [int]$BootTimeoutS = 90
)
$ErrorActionPreference = "Continue"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
Set-Location -LiteralPath $root
if ($Port -lt 7871 -or $Port -gt 7879) { Write-Host "FAIL port $Port is not a UI port (7871-7879)"; exit 2 }
New-Item -ItemType Directory -Force $OutDir | Out-Null
$out = (Resolve-Path $OutDir).Path
$script:fails = 0
$psBefore = (@(& curl.exe -s --max-time 5 http://127.0.0.1:11434/api/ps) -join "")
$busy = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
if ($busy.Count -gt 0) { Write-Host ("FAIL port {0} already has a listener: PID {1}" -f $Port, $busy[0].OwningProcess); exit 3 }
$env:PYTHONUTF8 = "1"
$env:GRADIO_ANALYTICS_ENABLED = "False"
$proc = $null
try {
    $proc = Start-Process -FilePath "python" -ArgumentList ("scripts\dev\finish\review_oi_r1_walk_app.py --port {0} --selected {1}" -f $Port, $Selected) `
        -WorkingDirectory $root -PassThru -WindowStyle Hidden -RedirectStandardOutput (Join-Path $out "walk_app_out.log") -RedirectStandardError (Join-Path $out "walk_app_err.log")
    $null = $proc.Handle
    $code = ""
    $deadline = (Get-Date).AddSeconds($BootTimeoutS)
    while ((Get-Date) -lt $deadline) {
        if ($proc.HasExited) { break }
        $code = (@(& curl.exe -s -o NUL -w "%{http_code}" --max-time 5 ("http://127.0.0.1:{0}/" -f $Port)) -join "")
        if ($code -eq "200") { break }
        Start-Sleep -Seconds 2
    }
    if ($code -ne "200") { Write-Host ("FAIL walk app did not answer HTTP 200 (last '{0}')" -f $code); $script:fails++; throw "boot failed" }
    Write-Host ("PASS walk app PID {0} answered HTTP 200 on port {1}" -f $proc.Id, $Port)
    $co = @(& python scripts\dev\finish\review_oi_r1_walk_probe.py --port $Port --out-dir $OutDir)
    $prc = $LASTEXITCODE
    $co | ForEach-Object { Write-Host ("  " + $_) }
    if ($prc -ne 0) { Write-Host ("FAIL probe exit {0}" -f $prc); $script:fails++ } else { Write-Host "PASS probe" }
} catch {
    Write-Host ("STOPPED: " + $_.Exception.Message)
} finally {
    if ($null -ne $proc) {
        $p2 = Get-Process -Id $proc.Id -ErrorAction SilentlyContinue
        if ($null -ne $p2 -and $p2.ProcessName -match '^pythonw?$') {
            Stop-Process -Id $proc.Id -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 3
            if (Get-Process -Id $proc.Id -ErrorAction SilentlyContinue) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue; Start-Sleep -Seconds 2 }
        }
        $alive = [bool](Get-Process -Id $proc.Id -ErrorAction SilentlyContinue)
        $portBusy = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue).Count
        if ((-not $alive) -and $portBusy -eq 0) { Write-Host ("PASS stopped walk app PID {0}; port {1} free" -f $proc.Id, $Port) }
        else { Write-Host ("FAIL walk app PID {0} alive={1}, listeners={2}" -f $proc.Id, $alive, $portBusy); $script:fails++ }
    }
    $psAfter = (@(& curl.exe -s --max-time 5 http://127.0.0.1:11434/api/ps) -join "")
    if ($psBefore -eq $psAfter -and $psAfter -match '"models":\[\]') { Write-Host ("PASS /api/ps unchanged: {0}" -f $psAfter) }
    else { Write-Host ("FAIL /api/ps before {0} after {1}" -f $psBefore, $psAfter); $script:fails++ }
}
if ($script:fails -gt 0) { exit 1 }
exit 0
