# PLAN_FINISH UI check driver (no GPU). Boots python app.py with TWIN_NO_WARM=1 on a UI port (7871-7879), takes
# headless screenshots through scripts\screenshot_tabs.ps1, optionally takes true 400 px shots and measures the Ask
# scrollWidth through scripts\dev\finish\cdp_shot.py, and checks view_api, then ALWAYS stops the app it started.
# Everything runs inside this one command, because the Claude Code PowerShell tool ends processes a command started
# once that command returns.
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\dev\finish\ui_check.ps1 -Port 7871 -OutDir scripts\dev\shots\x
#       [-Themes light,dark] [-Widths 1440] [-Tabs ask,status] [-Narrow] [-Measure] [-ViewApi] [-SaveSnapshot] [-NoShots]
# Why cdp_shot.py for 400 px: a Chrome --headless=new window can't be narrower than 500 px, so screenshot_tabs.ps1
# -Width 400 renders a 500 px layout cropped to 400; cdp_shot.py emulates a true 400 px CSS viewport.
# Output in OutDir: <theme>_<width>_<tab>.png, api_ps_before/after.json, lms_models_before/after.json, app_out.log,
# app_err.log, measure_ask_400_<theme>.json, view_api.json, ui_check.json (summary). Exit 0 when every check passed.
param(
    [Parameter(Mandatory = $true)][int]$Port,
    [Parameter(Mandatory = $true)][string]$OutDir,
    [string[]]$Themes = @("light"),
    [string[]]$Widths = @("1440"),
    [string[]]$Tabs = @("onboarding", "ask", "decide", "act", "see", "items", "eval", "status"),
    [switch]$Narrow,        # also Ask at a true 400 px in every theme (cdp_shot.py)
    [switch]$Measure,       # Ask document scrollWidth at a true 400 px in every theme must be <= 400
    [switch]$ViewApi,       # scripts\dev\finish\view_api_check.py (baseline + six new names, and the snapshot if present)
    [switch]$SaveSnapshot,  # write scripts\dev\finish\view_api_pre_c.json from this app (pre-restyle capture only)
    [switch]$NoShots,       # skip the 1440 px screenshots
    [int]$VirtualTimeMs = 20000,
    [int]$BootTimeoutS = 150
)
$ErrorActionPreference = "Continue"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
Set-Location -LiteralPath $root
function Split-List($v) { @($v | ForEach-Object { "$_" -split "," } | ForEach-Object { $_.Trim() } | Where-Object { $_ }) }
$Themes = Split-List $Themes
$Tabs = Split-List $Tabs
$WidthList = @(Split-List $Widths | ForEach-Object { [int]$_ })
if ($Port -lt 7871 -or $Port -gt 7879) { Write-Host "FAIL port $Port is not a UI port (7871-7879)"; exit 2 }
New-Item -ItemType Directory -Force $OutDir | Out-Null
$out = (Resolve-Path $OutDir).Path
$utf8 = New-Object System.Text.UTF8Encoding $false
$snapshot = Join-Path $root "scripts\dev\finish\view_api_pre_c.json"
$summary = [ordered]@{ port = $Port; out_dir = $OutDir; started = (Get-Date).ToString("o") }
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

$busy = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
if ($busy.Count -gt 0) {
    $owner = Get-Process -Id $busy[0].OwningProcess -ErrorAction SilentlyContinue
    Line "FAIL" ("port {0} already has a listener: PID {1} ({2}). Stop it only after confirming it is your own python app." -f $Port, $busy[0].OwningProcess, $owner.ProcessName)
    $summary.fails = @($fails)
    Save "ui_check.json" ($summary | ConvertTo-Json -Depth 6)
    exit 3
}

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
    $summary.boot_s = [math]::Round(((Get-Date) - $t0).TotalSeconds, 1)
    $summary.app_pid = $proc.Id
    if ($code -ne "200") {
        Line "FAIL" ("app did not answer HTTP 200 on port {0} (last code '{1}', exited {2}); see app_err.log" -f $Port, $code, $proc.HasExited)
        throw "boot failed"
    }
    Line "PASS" ("app PID {0} answered HTTP 200 on port {1} after {2} s (TWIN_NO_WARM=1)" -f $proc.Id, $Port, $summary.boot_s)

    if (-not $NoShots) {
        foreach ($t in $Themes) {
            foreach ($w in $WidthList) {
                $o = @(& powershell -NoProfile -ExecutionPolicy Bypass -File scripts\screenshot_tabs.ps1 -Port $Port -Theme $t -Width $w -Tabs ($Tabs -join ",") -VirtualTimeMs $VirtualTimeMs -OutDir $OutDir)
                $o | ForEach-Object { Write-Host ("  " + $_) }
            }
        }
    }

    if ($Narrow -or $Measure) {
        $m = [ordered]@{}
        foreach ($t in $Themes) {
            $mj = Join-Path $out ("measure_ask_400_{0}.json" -f $t)
            if (Test-Path -LiteralPath $mj) { Remove-Item -LiteralPath $mj -Force }
            $co = @(& python scripts\dev\finish\cdp_shot.py --port $Port --tabs ask --theme $t --width 400 --height 900 --out-dir $OutDir --json $mj)
            $co | ForEach-Object { Write-Host ("  " + $_) }
            $res = $null
            try { $res = @((Get-Content -LiteralPath $mj -Raw -Encoding UTF8 | ConvertFrom-Json).results)[0] } catch { }
            if ($null -ne $res -and $null -ne $res.scrollWidth) {
                $m[$t] = [ordered]@{ scrollWidth = [int]$res.scrollWidth; innerWidth = [int]$res.innerWidth; selectedTab = $res.selectedTab; overflowing = @($res.overflowing).Count }
                if ($Measure) {
                    if ([int]$res.innerWidth -ne 400 -or $res.selectedTab -ne "Ask") {
                        Line "FAIL" ("Ask at 400 px ({0}): not a valid measurement (innerWidth={1}, selected tab '{2}')" -f $t, $res.innerWidth, $res.selectedTab)
                    } elseif ([int]$res.scrollWidth -le 400) {
                        Line "PASS" ("Ask at 400 px ({0}): scrollWidth={1} innerWidth={2}" -f $t, $res.scrollWidth, $res.innerWidth)
                    } else {
                        Line "FAIL" ("Ask at 400 px ({0}): scrollWidth={1} > 400 (innerWidth={2}; {3} overflowing elements listed in {4})" -f $t, $res.scrollWidth, $res.innerWidth, @($res.overflowing).Count, $mj)
                    }
                }
            } else {
                $m[$t] = "no measurement ($mj)"
                if ($Measure) { Line "FAIL" ("Ask at 400 px ({0}): cdp_shot.py returned no measurement" -f $t) }
            }
        }
        $summary.measure = $m
    }

    $shots = New-Object System.Collections.Generic.List[string]
    Get-ChildItem -LiteralPath $out -Filter *.png | Sort-Object Name | ForEach-Object {
        $shots.Add(("{0} {1}" -f $_.Name, $_.Length))
        if ($_.Length -lt 5000) { Line "FAIL" ("screenshot {0} is only {1} bytes" -f $_.Name, $_.Length) }
    }
    if ($shots.Count -gt 0) { Line "PASS" ("{0} screenshots in {1}" -f $shots.Count, $OutDir) }
    $summary.screenshots = @($shots)

    if ($ViewApi -or $SaveSnapshot) {
        $vargs = @("scripts\dev\finish\view_api_check.py", "$Port", (Join-Path $OutDir "view_api.json"))
        if ($SaveSnapshot) { $vargs += @("--save-snapshot", "scripts\dev\finish\view_api_pre_c.json") }
        elseif (Test-Path -LiteralPath $snapshot) { $vargs += @("--snapshot", "scripts\dev\finish\view_api_pre_c.json") }
        $vo = @(& python @vargs)
        $vrc = $LASTEXITCODE
        $vo | ForEach-Object { Write-Host ("  " + $_) }
        $summary.view_api = [ordered]@{ exit = $vrc; output = @($vo) }
        if ($vrc -eq 0) { Line "PASS" "view_api check (names, parameters, returns)" } else { Line "FAIL" ("view_api check exit {0}" -f $vrc) }
    }
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
        $summary.app_stopped = -not $alive
        $summary.port_free_after = ($portBusy -eq 0)
        if ((-not $alive) -and $portBusy -eq 0) { Line "PASS" ("stopped app PID {0}; port {1} free" -f $proc.Id, $Port) }
        else { Line "FAIL" ("app PID {0} alive={1}, listeners on {2}: {3}" -f $proc.Id, $alive, $Port, $portBusy) }
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
    Save "ui_check.json" ($summary | ConvertTo-Json -Depth 6)
    Write-Host ("ui_check: {0} ({1} fails) -> {2}\ui_check.json" -f $(if ($fails.Count -eq 0) { "PASS" } else { "FAIL" }), $fails.Count, $OutDir)
}
if ($fails.Count -gt 0) { exit 1 }
exit 0
