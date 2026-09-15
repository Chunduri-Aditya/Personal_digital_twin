# Review r1 of lane onboarding_items (docs/PLAN_FINISH.md P4, no GPU). Boots python app.py with TWIN_NO_WARM=1 on a
# UI port (7871-7879), runs scripts\dev\finish\review_oi_r1_capture.py against it, and ALWAYS stops the app it started
# (the same boot and stop discipline as ui_check.ps1: everything runs inside this one command). Saves /api/ps and
# /api/v0/models bodies before and after.
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\dev\finish\review_oi_r1_harness.ps1 -Port 7876 -OutDir <dir>
param(
    [Parameter(Mandatory = $true)][int]$Port,
    [Parameter(Mandatory = $true)][string]$OutDir,
    [int]$BootTimeoutS = 150
)
$ErrorActionPreference = "Continue"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
Set-Location -LiteralPath $root
if ($Port -lt 7871 -or $Port -gt 7879) { Write-Host "FAIL port $Port is not a UI port (7871-7879)"; exit 2 }
New-Item -ItemType Directory -Force $OutDir | Out-Null
$out = (Resolve-Path $OutDir).Path
$utf8 = New-Object System.Text.UTF8Encoding $false
function Save([string]$name, [string]$text) { [System.IO.File]::WriteAllText((Join-Path $out $name), $text, $utf8) }
function Get-Bodies {
    $ps = (@(& curl.exe -s --max-time 5 http://127.0.0.1:11434/api/ps) -join "")
    $lms = (@(& curl.exe -s --max-time 5 http://127.0.0.1:1234/api/v0/models) -join "")
    $loaded = "no JSON"
    try { $loaded = ((@(($lms | ConvertFrom-Json).data | Where-Object { $_.state -eq "loaded" } | ForEach-Object { $_.id })) -join ",") } catch { }
    return @($ps, $lms, $loaded)
}
$script:fails = 0
$before = Get-Bodies
Save "api_ps_before.json" $before[0]
Save "lms_models_before.json" $before[1]
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
    if ($code -ne "200") { Write-Host ("FAIL app did not answer HTTP 200 on port {0} (last '{1}')" -f $Port, $code); $script:fails++; throw "boot failed" }
    Write-Host ("PASS app PID {0} answered HTTP 200 on port {1} after {2} s (TWIN_NO_WARM=1)" -f $proc.Id, $Port, [math]::Round(((Get-Date) - $t0).TotalSeconds, 1))
    $co = @(& python scripts\dev\finish\review_oi_r1_capture.py --port $Port --out-dir $OutDir)
    $crc = $LASTEXITCODE
    $co | ForEach-Object { Write-Host ("  " + $_) }
    if ($crc -ne 0) { Write-Host ("FAIL capture exit {0}" -f $crc); $script:fails++ } else { Write-Host "PASS capture" }
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
        else { Write-Host ("FAIL app PID {0} alive={1}, listeners on {2}: {3}" -f $proc.Id, $alive, $Port, $portBusy); $script:fails++ }
    }
    $after = Get-Bodies
    Save "api_ps_after.json" $after[0]
    Save "lms_models_after.json" $after[1]
    if ($before[0] -eq $after[0] -and $after[0] -match '"models":\[\]') { Write-Host ("PASS /api/ps unchanged: {0}" -f $after[0]) }
    else { Write-Host ("FAIL /api/ps before {0} after {1}" -f $before[0], $after[0]); $script:fails++ }
    if ($before[2] -eq $after[2]) { Write-Host ("PASS LM Studio loaded list unchanged: [{0}]" -f $after[2]) }
    else { Write-Host ("FAIL LM Studio loaded before [{0}] after [{1}]" -f $before[2], $after[2]); $script:fails++ }
}
if ($script:fails -gt 0) { exit 1 }
exit 0
