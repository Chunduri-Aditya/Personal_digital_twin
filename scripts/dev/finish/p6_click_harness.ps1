# P6 docs mode (no GPU, no model): boots python app.py with TWIN_NO_WARM=1 on a UI port, runs
# scripts\dev\finish\p6_click_probe.py (real mouse clicks on the Walkthrough and the tab strip, fold positions, the blue
# dot), and ALWAYS stops the app it started, all inside this one command (the ui_check.ps1 boot and stop discipline).
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\dev\finish\p6_click_harness.ps1 -Port 7871 -OutDir scripts\dev\demo\click_probe
param(
    [Parameter(Mandatory = $true)][int]$Port,
    [Parameter(Mandatory = $true)][string]$OutDir,
    [string]$Probe = "p6_click_probe.py",   # or p6_tick_probe.py (Status 5 s refresh vs the Last action line)
    [int]$BootTimeoutS = 150
)
$ErrorActionPreference = "Continue"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
Set-Location -LiteralPath $root
if ($Port -lt 7871 -or $Port -gt 7879) { Write-Host "FAIL port $Port is not a UI port (7871-7879)"; exit 2 }
if ($Probe -notmatch '^p6_[a-z_]+_probe\.py$') { Write-Host "FAIL probe $Probe is not a scripts\dev\finish\p6_*_probe.py file"; exit 2 }
New-Item -ItemType Directory -Force $OutDir | Out-Null
$out = (Resolve-Path $OutDir).Path
$script:fails = 0
function Get-LmsLoaded {
    $lms = (@(& curl.exe -s --max-time 5 http://127.0.0.1:1234/api/v0/models) -join "")
    try { return ((@(($lms | ConvertFrom-Json).data | Where-Object { $_.state -eq "loaded" } | ForEach-Object { $_.id })) -join ",") } catch { return "no JSON" }
}
$psBefore = (@(& curl.exe -s --max-time 5 http://127.0.0.1:11434/api/ps) -join "")
$lmsBefore = Get-LmsLoaded
Write-Host ("before: /api/ps {0} | LM Studio loaded [{1}]" -f $psBefore, $lmsBefore)
$busy = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
if ($busy.Count -gt 0) { Write-Host ("FAIL port {0} already has a listener: PID {1}" -f $Port, $busy[0].OwningProcess); exit 3 }
$env:PYTHONUTF8 = "1"
$env:TWIN_NO_WARM = "1"
$env:GRADIO_ANALYTICS_ENABLED = "False"
$proc = $null
try {
    $t0 = Get-Date
    $proc = Start-Process -FilePath "python" -ArgumentList ("app.py --port {0}" -f $Port) -WorkingDirectory $root -PassThru `
        -WindowStyle Hidden -RedirectStandardOutput (Join-Path $out "app_out.log") -RedirectStandardError (Join-Path $out "app_err.log")
    $null = $proc.Handle
    $code = ""
    $deadline = (Get-Date).AddSeconds($BootTimeoutS)
    while ((Get-Date) -lt $deadline) {
        if ($proc.HasExited) { break }
        $code = (@(& curl.exe -s -o NUL -w "%{http_code}" --max-time 5 ("http://127.0.0.1:{0}/" -f $Port)) -join "")
        if ($code -eq "200") { break }
        Start-Sleep -Seconds 2
    }
    if ($code -ne "200") { Write-Host ("FAIL app did not answer HTTP 200 (last '{0}', exited {1})" -f $code, $proc.HasExited); $script:fails++; throw "boot failed" }
    Write-Host ("PASS app PID {0} answered HTTP 200 on port {1} after {2:N1} s (TWIN_NO_WARM=1)" -f $proc.Id, $Port, ((Get-Date) - $t0).TotalSeconds)
    $co = @(& python (Join-Path "scripts\dev\finish" $Probe) --port $Port --out-dir $OutDir)
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
        if ((-not $alive) -and $portBusy -eq 0) { Write-Host ("PASS stopped app PID {0}; port {1} free" -f $proc.Id, $Port) }
        else { Write-Host ("FAIL app PID {0} alive={1}, listeners={2}" -f $proc.Id, $alive, $portBusy); $script:fails++ }
    }
    $psAfter = (@(& curl.exe -s --max-time 5 http://127.0.0.1:11434/api/ps) -join "")
    $lmsAfter = Get-LmsLoaded
    if ($psBefore -eq $psAfter -and $psAfter -match '"models":\[\]') { Write-Host ("PASS /api/ps unchanged: {0}" -f $psAfter) }
    else { Write-Host ("FAIL /api/ps before {0} after {1}" -f $psBefore, $psAfter); $script:fails++ }
    if ($lmsBefore -eq $lmsAfter) { Write-Host ("PASS LM Studio loaded list unchanged: [{0}]" -f $lmsAfter) }
    else { Write-Host ("FAIL LM Studio loaded before [{0}] after [{1}]" -f $lmsBefore, $lmsAfter); $script:fails++ }
}
if ($script:fails -gt 0) { exit 1 }
exit 0
