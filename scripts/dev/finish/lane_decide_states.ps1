# P4 decide lane: preview the Decide tab's result states without a model. For each state this boots
# scripts\dev\finish\lane_decide_preview.py (the real app layout plus a recorded Decide result, TWIN_NO_WARM=1) on a UI
# port, captures it with scripts\dev\finish\lane_decide_capture.py, and ALWAYS stops the process it started. Same guards
# as ui_check.ps1: UI ports 7871-7879 only, /api/ps and LM Studio bodies saved before and after, only a verified python
# PID is stopped, and the port must be free afterwards. Everything runs inside this one command.
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\dev\finish\lane_decide_states.ps1 -Port 7873
#       -OutDir scripts\dev\shots\lane_decide\states [-States verdict,b2,error,crash,empty] [-Themes light,dark] [-Dump]
param(
    [Parameter(Mandatory = $true)][int]$Port,
    [Parameter(Mandatory = $true)][string]$OutDir,
    [string[]]$States = @("verdict", "b2", "error", "crash", "empty"),
    [string[]]$Themes = @("light", "dark"),
    [switch]$Dump,
    [int]$BootTimeoutS = 150
)
$ErrorActionPreference = "Continue"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
Set-Location -LiteralPath $root
function Split-List($v) { @($v | ForEach-Object { "$_" -split "," } | ForEach-Object { $_.Trim() } | Where-Object { $_ }) }
$States = Split-List $States
$Themes = Split-List $Themes
if ($Port -lt 7871 -or $Port -gt 7879) { Write-Host "FAIL port $Port is not a UI port (7871-7879)"; exit 2 }
New-Item -ItemType Directory -Force $OutDir | Out-Null
$out = (Resolve-Path $OutDir).Path
$utf8 = New-Object System.Text.UTF8Encoding $false
$summary = [ordered]@{ port = $Port; out_dir = $OutDir; started = (Get-Date).ToString("o"); states = [ordered]@{} }
$fails = New-Object System.Collections.Generic.List[string]

function Save([string]$name, [string]$text) { [System.IO.File]::WriteAllText((Join-Path $out $name), $text, $utf8) }
function Line([string]$status, [string]$text) {
    Write-Host ("{0} {1}" -f $status, $text)
    if ($status -eq "FAIL") { $fails.Add($text) }
}
function Get-Bodies {
    $ps = (@(& curl.exe -s --max-time 5 http://127.0.0.1:11434/api/ps) -join "")
    $lms = (@(& curl.exe -s --max-time 5 http://127.0.0.1:1234/api/v0/models) -join "")
    $loaded = "no JSON"
    try { $loaded = ((@(($lms | ConvertFrom-Json).data | Where-Object { $_.state -eq "loaded" } | ForEach-Object { $_.id })) -join ",") } catch { }
    return @($ps, $lms, $loaded)
}

$before = Get-Bodies
Save "api_ps_before.json" $before[0]
Save "lms_models_before.json" $before[1]
$summary.api_ps_before = $before[0]
$summary.lms_loaded_before = $before[2]

$env:PYTHONUTF8 = "1"
$env:TWIN_NO_WARM = "1"
$env:GRADIO_ANALYTICS_ENABLED = "False"
foreach ($s in $States) {
    $row = [ordered]@{}
    $busy = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
    if ($busy.Count -gt 0) {
        Line "FAIL" ("{0}: port {1} already has a listener (PID {2}); not starting" -f $s, $Port, $busy[0].OwningProcess)
        $summary.states[$s] = $row
        continue
    }
    $proc = $null
    try {
        $t0 = Get-Date
        $proc = Start-Process -FilePath "python" -ArgumentList ("scripts\dev\finish\lane_decide_preview.py --port {0} --state {1}" -f $Port, $s) `
            -WorkingDirectory $root -PassThru -WindowStyle Hidden `
            -RedirectStandardOutput (Join-Path $out ("preview_{0}_out.log" -f $s)) -RedirectStandardError (Join-Path $out ("preview_{0}_err.log" -f $s))
        $null = $proc.Handle
        $code = ""
        $deadline = (Get-Date).AddSeconds($BootTimeoutS)
        while ((Get-Date) -lt $deadline) {
            if ($proc.HasExited) { break }
            $code = (@(& curl.exe -s -o NUL -w "%{http_code}" --max-time 5 ("http://127.0.0.1:{0}/" -f $Port)) -join "")
            if ($code -eq "200") { break }
            Start-Sleep -Seconds 2
        }
        $row.boot_s = [math]::Round(((Get-Date) - $t0).TotalSeconds, 1)
        $row.pid = $proc.Id
        if ($code -ne "200") {
            Line "FAIL" ("{0}: preview did not answer HTTP 200 on port {1} (last code '{2}', exited {3}); see preview_{0}_err.log" -f $s, $Port, $code, $proc.HasExited)
            throw "boot failed"
        }
        Line "PASS" ("{0}: preview PID {1} answered HTTP 200 on port {2} after {3} s (TWIN_NO_WARM=1)" -f $s, $proc.Id, $Port, $row.boot_s)
        $cargs = @("scripts\dev\finish\lane_decide_capture.py", "--port", "$Port", "--state", $s, "--out-dir", $OutDir, "--themes", ($Themes -join ","))
        if ($Dump) { $cargs += "--dump" }
        $co = @(& python @cargs)
        $crc = $LASTEXITCODE
        $co | ForEach-Object { Write-Host ("  " + $_) }
        $row.capture = [ordered]@{ exit = $crc; output = @($co) }
        if ($crc -eq 0) { Line "PASS" ("{0}: capture" -f $s) } else { Line "FAIL" ("{0}: capture exit {1}" -f $s, $crc) }
    } catch {
        Write-Host ("STOPPED {0}: {1}" -f $s, $_.Exception.Message)
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
            $row.stopped = -not $alive
            $row.port_free_after = ($portBusy -eq 0)
            if ((-not $alive) -and $portBusy -eq 0) { Line "PASS" ("{0}: stopped preview PID {1}; port {2} free" -f $s, $proc.Id, $Port) }
            else { Line "FAIL" ("{0}: preview PID {1} alive={2}, listeners on {3}: {4}" -f $s, $proc.Id, $alive, $Port, $portBusy) }
        }
        $summary.states[$s] = $row
    }
}
$after = Get-Bodies
Save "api_ps_after.json" $after[0]
Save "lms_models_after.json" $after[1]
$summary.api_ps_after = $after[0]
$summary.lms_loaded_after = $after[2]
if ($before[0] -eq $after[0] -and $after[0] -match '"models":\[\]') { Line "PASS" ("/api/ps unchanged: {0}" -f $after[0]) }
else { Line "FAIL" ("/api/ps before {0} after {1}" -f $before[0], $after[0]) }
if ($before[2] -eq $after[2]) { Line "PASS" ("LM Studio loaded list unchanged: [{0}]" -f $after[2]) }
else { Line "FAIL" ("LM Studio loaded before [{0}] after [{1}]" -f $before[2], $after[2]) }
$summary.lms_body_identical = ($before[1] -eq $after[1])
$summary.fails = @($fails)
$summary.ended = (Get-Date).ToString("o")
Save "states.json" ($summary | ConvertTo-Json -Depth 6)
Write-Host ("lane_decide_states: {0} ({1} fails) -> {2}\states.json" -f $(if ($fails.Count -eq 0) { "PASS" } else { "FAIL" }), $fails.Count, $OutDir)
if ($fails.Count -gt 0) { exit 1 }
exit 0
