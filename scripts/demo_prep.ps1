# Demo prep for PLAN_DEMO Session B (docs/PLAN_DEMO.md, run sheet docs/DEMO.md). Windows PowerShell 5.1.
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\demo_prep.ps1 [-WarmOnly] [-Port 7861]
# T-10 (no switch), 7 PASS lines in this order:
#   Ollama up -> LM Studio server up (started with "lms server start --port 1234 --bind 127.0.0.1" when port 1234
#   refuses) -> no other twin app on ports Port..Port+9 (a python listener that app.pid does not record is a FAIL)
#   -> scripts\free_gpu.ps1 -> GPU <= MaxGpuMiB (default 200 MiB; check_servers.ps1 parsing) -> profile lint and
#   index/digest fresh (python scripts\demo_rehearse.py --check-profile, read-only) -> python app.py in its own window
#   (PID -> scripts\dev\demo\app.pid, bound port -> scripts\dev\demo\app.port) -> app HTTP 200.
#   A live app recorded in app.pid is refused right after the LM Studio line, before anything touches the GPU. A
#   recorded PID counts only when it is a python process started before app.pid was written (Windows reuses PIDs).
# T-5 (-WarmOnly), 4 PASS lines: app running (app.pid + app.port) -> LM Studio server up -> live_drive.py warm decide
#   -> qwen3-8b-8k in Ollama /api/ps.
# -MaxGpuMiB N raises the idle-GPU gate when a projector or external display on the NVIDIA GPU holds VRAM.
# Output: one line per check, "PASS <check>" or "FAIL <check>: <reason>; <next action>"; diagnostics are indented
# and also written to scripts\dev\demo\prep_<yyyyMMdd-HHmmss>.log. Stops at the first FAIL (exit 1); exit 0 only when
# every check line is PASS. Never stops a process by name, never changes OLLAMA_* variables, never writes data\.
param(
    [switch]$WarmOnly,
    [int]$Port = 7861,
    [int]$MaxGpuMiB = 200
)
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root

$demoDir = Join-Path $root "scripts\dev\demo"
New-Item -ItemType Directory -Force $demoDir | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$logPath = Join-Path $demoDir ("prep_{0}.log" -f $stamp)
$pidFile = Join-Path $demoDir "app.pid"
$portFile = Join-Path $demoDir "app.port"
$lms = Join-Path $env:LOCALAPPDATA "Programs\LM Studio\resources\app\.webpack\lms.exe"
$ollamaUrl = "http://127.0.0.1:11434"
$lmsUrl = "http://127.0.0.1:1234"
$utf8NoBom = New-Object System.Text.UTF8Encoding $false
$env:PYTHONUTF8 = "1"

# ---- output helpers ------------------------------------------------------------------------------------------------
function Write-Log([string]$text) {
    try { [System.IO.File]::AppendAllText($logPath, $text + "`r`n", $utf8NoBom) } catch { }
}
function Say([string]$text) {
    Write-Host $text
    Write-Log $text
}
function Show-Detail($lines, [int]$max = 60) {
    $all = @($lines | Where-Object { $null -ne $_ })
    $shown = $all
    if ($all.Count -gt $max) { $shown = $all[($all.Count - $max)..($all.Count - 1)] }
    if ($all.Count -gt $max) { Say ("    ... ({0} earlier lines in the log)" -f ($all.Count - $max)) }
    foreach ($l in $all) { if ($shown -notcontains $l) { Write-Log ("    " + [string]$l) } }
    foreach ($l in $shown) { Say ("    " + [string]$l) }
}
function Pass([string]$check) { Say ("PASS " + $check) }
function Fail([string]$check, [string]$reason) {
    Say ("FAIL {0}: {1}" -f $check, $reason)
    Say ("    log: " + $logPath)
    exit 1
}

# ---- HTTP and process helpers --------------------------------------------------------------------------------------
function Get-Body([string]$url, [int]$timeoutSec = 5) {
    $body = & curl.exe -s --max-time $timeoutSec $url
    $code = $LASTEXITCODE
    return [pscustomobject]@{ CurlExit = $code; Text = ((@($body) | Where-Object { $null -ne $_ }) -join "`n") }
}
function ConvertFrom-JsonSafe([string]$text) {
    if (-not $text) { return $null }
    try { return ($text | ConvertFrom-Json) } catch { return $null }
}
function Get-HttpCode([string]$url, [int]$timeoutSec = 5) {
    $code = & curl.exe -s -o NUL -w "%{http_code}" --max-time $timeoutSec $url
    return ([string]$code).Trim()
}
function Quote-Arg([string]$a) {
    if ($a -match '[\s"]') { return '"' + ($a -replace '"', '\"') + '"' }
    return $a
}
# Start a child with stdout/stderr redirected to files under scripts\dev\demo, wait up to $timeoutSec, kill only that
# child on timeout. Returns ExitCode (null on timeout), TimedOut, Out and Err (line arrays), ProcId.
function Invoke-Child([string]$file, [string]$argString, [int]$timeoutSec, [string]$tag) {
    $out = Join-Path $demoDir ("prep_{0}_{1}.out.txt" -f $stamp, $tag)
    $err = Join-Path $demoDir ("prep_{0}_{1}.err.txt" -f $stamp, $tag)
    Write-Log ("    > {0} {1}" -f $file, $argString)
    try {
        $p = Start-Process -FilePath $file -ArgumentList $argString -WorkingDirectory $root -NoNewWindow -PassThru `
            -RedirectStandardOutput $out -RedirectStandardError $err -ErrorAction Stop
    } catch {
        return [pscustomobject]@{ ExitCode = $null; TimedOut = $false; Out = @(); Err = @([string]$_.Exception.Message); ProcId = 0; Started = $false }
    }
    $null = $p.Handle
    $timedOut = $false
    if (-not $p.WaitForExit($timeoutSec * 1000)) {
        $timedOut = $true
        try { $p.Kill() } catch { }
        $null = $p.WaitForExit(10000)
    }
    $code = $null
    if (-not $timedOut) { $p.WaitForExit(); $code = $p.ExitCode }
    $stdout = @()
    $stderr = @()
    try { if (Test-Path -LiteralPath $out) { $stdout = @(Get-Content -LiteralPath $out -Encoding UTF8 -ErrorAction Stop) } } catch { }
    try { if (Test-Path -LiteralPath $err) { $stderr = @(Get-Content -LiteralPath $err -Encoding UTF8 -ErrorAction Stop) } } catch { }
    return [pscustomobject]@{ ExitCode = $code; TimedOut = $timedOut; Out = $stdout; Err = $stderr; ProcId = $p.Id; Started = $true }
}
$script:staleNoted = $false
function Get-LivePid([string]$path) {
    # The recorded PID counts as the app only when it is a python process that started before app.pid was written:
    # after a reboot Windows can hand the old number to an unrelated program, which must never be stopped.
    if (-not (Test-Path -LiteralPath $path)) { return $null }
    $raw = [string](Get-Content -LiteralPath $path -TotalCount 1)
    $n = 0
    if (-not [int]::TryParse($raw.Trim(), [ref]$n)) { return $null }
    if ($n -le 0) { return $null }
    $proc = Get-Process -Id $n -ErrorAction SilentlyContinue
    if ($null -eq $proc) { return $null }
    $why = ""
    if ($proc.ProcessName -notmatch '^pythonw?$') {
        $why = "now belongs to {0}, not python" -f $proc.ProcessName
    } else {
        try {
            if ($proc.StartTime -gt (Get-Item -LiteralPath $path).LastWriteTime.AddSeconds(5)) {
                $why = "is a python process started after app.pid was written"
            }
        } catch { $why = "has no readable start time" }
    }
    if ($why) {
        if (-not $script:staleNoted) {
            Say ("    note: scripts\dev\demo\app.pid names PID {0}, which {1}; treating app.pid as stale (nothing is stopped)" -f $n, $why)
            $script:staleNoted = $true
        }
        return $null
    }
    return $proc
}
function Read-PortFile {
    if (-not (Test-Path -LiteralPath $portFile)) { return 0 }
    $raw = [string](Get-Content -LiteralPath $portFile -TotalCount 1)
    $n = 0
    if ([int]::TryParse($raw.Trim(), [ref]$n)) { return $n }
    return 0
}

Write-Log ("demo_prep.ps1 {0} WarmOnly={1} Port={2} root={3}" -f (Get-Date -Format "s"), [bool]$WarmOnly, $Port, $root)

# =====================================================================================================================
# -WarmOnly (T-5)
# =====================================================================================================================
if ($WarmOnly) {
    $check = "app running"
    $app = Get-LivePid $pidFile
    if ($null -eq $app) {
        Fail $check "no live process in scripts\dev\demo\app.pid; run scripts\demo_prep.ps1 without -WarmOnly first"
    }
    $appPort = Read-PortFile
    if ($appPort -le 0) {
        Fail $check ("scripts\dev\demo\app.port is missing or unreadable (app PID {0}); stop PID {0}, then run scripts\demo_prep.ps1 without -WarmOnly" -f $app.Id)
    }
    $url = "http://127.0.0.1:{0}/" -f $appPort
    $code = Get-HttpCode $url 5
    if ($code -ne "200") {
        Fail $check ("{0} answered HTTP '{1}' (PID {2}); look at the app window, or stop PID {2} and rerun scripts\demo_prep.ps1" -f $url, $code, $app.Id)
    }
    Pass ("{0} at {1} (PID {2})" -f $check, $url, $app.Id)

    # Decide embeds the situation with LM Studio's nomic model: a server that died after T-10 shows up only as
    # **Error:** at B2.1 unless it is caught here.
    $check = "LM Studio server up"
    $lmsNow = Get-Body ($lmsUrl + "/api/v0/models") 5
    $lmsNowJson = ConvertFrom-JsonSafe $lmsNow.Text
    if ($null -eq $lmsNowJson) {
        Fail $check ("{0}/api/v0/models returned no JSON (curl exit {1}); Decide (B2.1) would show **Error:** and Say it would fall back to llama3.2:3b. Rerun scripts\demo_prep.ps1: its LM Studio line starts the server, then it stops at 'app already running', which is expected here; then rerun -WarmOnly" -f $lmsUrl, $lmsNow.CurlExit)
    }
    Pass ("{0} ({1} models listed)" -f $check, @($lmsNowJson.data).Count)

    $check = "warm decide"
    $w = Invoke-Child "python" ("scripts\dev\live_drive.py warm decide --port {0}" -f $appPort) 180 "warm_decide"
    Show-Detail ($w.Out | Where-Object { $_ -match "Last action|Warm:|Error|skipped|===" })
    Write-Log "    --- live_drive stdout ---"
    foreach ($l in $w.Out) { Write-Log ("    " + $l) }
    if ($w.Err.Count -gt 0) { Write-Log "    --- live_drive stderr ---"; foreach ($l in $w.Err) { Write-Log ("    " + $l) } }
    if (-not $w.Started) { Fail $check ("could not start python: {0}; check that python is on PATH" -f ($w.Err -join " ")) }
    if ($w.TimedOut) {
        Fail $check ("live_drive.py warm decide did not finish in 180 s (killed PID {0}); a turn may be queued on the gpu queue: look at the app window, then rerun -WarmOnly" -f $w.ProcId)
    }
    if ($w.ExitCode -ne 0) {
        $last = @($w.Err | Where-Object { $_ -and $_.Trim() }) | Select-Object -Last 3
        Fail $check ("live_drive.py exit {0}: {1}; check the app window and the log, then rerun -WarmOnly" -f $w.ExitCode, ($last -join " | "))
    }
    $outText = $w.Out -join "`n"
    if ($outText -match "skipped: TWIN_NO_WARM=1") {
        Fail $check ("the app runs with TWIN_NO_WARM=1 so nothing was loaded; stop PID {0} and rerun scripts\demo_prep.ps1 (it clears the switch)" -f $app.Id)
    }
    if ($outText -match "\*\*Error:\*\*") {
        $errLine = @($w.Out | Where-Object { $_ -match "\*\*Error:\*\*" }) | Select-Object -First 1
        Fail $check ("the app reported {0}; check Ollama and the app window, then rerun -WarmOnly" -f $errLine)
    }
    Pass ("{0} (live_drive exit 0)" -f $check)

    $check = "qwen3-8b-8k loaded"
    $found = $null
    $psText = ""
    $deadline = (Get-Date).AddSeconds(60)
    while ($true) {
        $ps = Get-Body ($ollamaUrl + "/api/ps") 5
        $psText = $ps.Text
        $psJson = ConvertFrom-JsonSafe $psText
        if ($null -ne $psJson -and $null -ne $psJson.models) {
            foreach ($m in @($psJson.models)) {
                $nm = [string]$m.name
                $md = [string]$m.model
                if ($nm -eq "qwen3-8b-8k" -or $nm -eq "qwen3-8b-8k:latest" -or $md -eq "qwen3-8b-8k" -or $md -eq "qwen3-8b-8k:latest") { $found = $m }
            }
        }
        if ($null -ne $found) { break }
        if ((Get-Date) -ge $deadline) { break }
        Start-Sleep -Seconds 2
    }
    Show-Detail @("Ollama /api/ps: " + $psText)
    if ($null -eq $found) {
        Fail $check "Ollama /api/ps does not list qwen3-8b-8k after 60 s; select the Decide tab and wait for 'Pre-warmed qwen3_8k', or rerun -WarmOnly"
    }
    $vram = ""
    try { $vram = "{0:N1} GB in VRAM" -f ([double]$found.size_vram / 1e9) } catch { }
    Pass ("{0} ({1}, expires_at {2}, {3})" -f $check, $found.name, $found.expires_at, $vram)
    Say "    keep-alive is 10 min and the heartbeat holds it only once a model tab is selected: click Decide and wait for 'Pre-warmed qwen3_8k' before pressing B1"
    exit 0
}

# =====================================================================================================================
# T-10 prep
# =====================================================================================================================
# 1. Ollama up
$check = "Ollama up"
$tags = Get-Body ($ollamaUrl + "/api/tags") 5
$tagsJson = ConvertFrom-JsonSafe $tags.Text
if ($null -eq $tagsJson) {
    Fail $check ("{0}/api/tags did not return JSON (curl exit {1}); start the Ollama app (Start menu, or `"{2}`"), wait 10 s, rerun" -f $ollamaUrl, $tags.CurlExit, (Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama app.exe"))
}
$onDisk = @($tagsJson.models | ForEach-Object { ([string]$_.name) -replace ":latest$", "" })
$needed = @("qwen3-8b-8k", "hermes3:8b", "llama3.2:1b", "llama3.2:3b", "nomic-embed-text", "qwen3.5:4b-q8_0")
$missing = @($needed | Where-Object { $onDisk -notcontains $_ })
Pass ("{0} ({1} models on disk)" -f $check, $onDisk.Count)
if ($missing.Count -gt 0) { Say ("    WARNING demo models not on disk: {0}" -f ($missing -join ", ")) }

# 2. LM Studio server up (start it when port 1234 refuses)
$check = "LM Studio server up"
$lmsModels = Get-Body ($lmsUrl + "/api/v0/models") 5
$lmsJson = ConvertFrom-JsonSafe $lmsModels.Text
$startedLms = $false
if ($null -eq $lmsJson) {
    if ($lmsModels.CurlExit -eq 0 -and $lmsModels.Text) {
        Show-Detail @("body: " + $lmsModels.Text)
        Fail $check ("{0}/api/v0/models answered but not with JSON; if it says 401 turn off 'Require Authentication' in LM Studio Developer > Server Settings, then rerun" -f $lmsUrl)
    }
    if (-not (Test-Path -LiteralPath $lms)) {
        Fail $check ("port 1234 refused and the lms CLI is missing at {0}; start the LM Studio server from the app (Developer > Start server), then rerun" -f $lms)
    }
    Say ("    port 1234 refused (curl exit {0}); starting: lms server start --port 1234 --bind 127.0.0.1" -f $lmsModels.CurlExit)
    $t0 = Get-Date
    # 20 s is enough for the CLI to hand off; some lms builds stay in the foreground, and the /api/v0/models poll below
    # decides PASS or FAIL either way.
    $s = Invoke-Child "cmd" ("/c echo y| `"{0}`" server start --port 1234 --bind 127.0.0.1" -f $lms) 20 "lms_server_start"
    Show-Detail ($s.Out + $s.Err) 20
    if ($s.TimedOut) { Say ("    lms server start did not return in 20 s (killed cmd PID {0}); polling the server anyway" -f $s.ProcId) }
    $deadline = (Get-Date).AddSeconds(60)
    while ($true) {
        $lmsModels = Get-Body ($lmsUrl + "/api/v0/models") 5
        $lmsJson = ConvertFrom-JsonSafe $lmsModels.Text
        if ($null -ne $lmsJson) { break }
        if ((Get-Date) -ge $deadline) { break }
        Start-Sleep -Seconds 2
    }
    if ($null -eq $lmsJson) {
        Fail $check ("{0}/api/v0/models still returns no JSON 60 s after lms server start (curl exit {1}); open LM Studio, start the server on port 1234 (Developer tab), then rerun" -f $lmsUrl, $lmsModels.CurlExit)
    }
    $startedLms = $true
    $elapsed = [int]((Get-Date) - $t0).TotalSeconds
}
$loadedLms = @($lmsJson.data | Where-Object { $_.state -eq "loaded" } | ForEach-Object { [string]$_.id })
$listedLms = @($lmsJson.data | ForEach-Object { [string]$_.id })
if ($startedLms) {
    Pass ("{0} (started with lms server start in {1} s; {2} models listed)" -f $check, $elapsed, $listedLms.Count)
} else {
    Pass ("{0} ({1} models listed, {2} loaded)" -f $check, $listedLms.Count, $loadedLms.Count)
}
foreach ($id in @("l3-8b-stheno-v3.2", "text-embedding-nomic-embed-text-v1.5")) {
    if ($listedLms -notcontains $id) { Say ("    WARNING LM Studio does not list {0}" -f $id) }
}

# Refuse a second app BEFORE touching the GPU: free_gpu.ps1 would unload models under a live demo app. Servers are
# checked (and LM Studio started) first, so a mid-demo rerun still repairs LM Studio.
$running = Get-LivePid $pidFile
if ($null -ne $running) {
    $oldPort = Read-PortFile
    $where = "(port unknown)"
    if ($oldPort -gt 0) { $where = "http://127.0.0.1:{0}/" -f $oldPort }
    Fail "app HTTP 200" ("app already running at {0} (PID {1}, {2}); servers checked above, GPU left untouched; keep using it, or stop PID {1} and rerun" -f $where, $running.Id, $running.ProcessName)
}

# No other twin app on the app's port range. A python app that app.pid does not record (started by hand, or left by
# another session) runs its own heartbeat: once any model tab was selected in it, it re-warms that model on its own
# schedule and evicts the demo's model mid-demo, and the new app would silently bind the next port.
$check = ("no other twin app on ports {0}-{1}" -f $Port, ($Port + 9))
$listeners = @()
try {
    $listeners = @(Get-NetTCPConnection -State Listen -ErrorAction Stop | Where-Object {
        $_.LocalPort -ge $Port -and $_.LocalPort -le ($Port + 9) })
} catch {
    Say ("    WARNING could not list listeners ({0}); port check skipped" -f $_.Exception.Message)
}
$owners = @{}          # PID -> ports; a plain hashtable (an [ordered] one would treat an int key as a position)
foreach ($l in $listeners) {
    $o = [int]$l.OwningProcess
    if (-not $owners.ContainsKey($o)) { $owners[$o] = @() }
    if ($owners[$o] -notcontains [int]$l.LocalPort) { $owners[$o] += [int]$l.LocalPort }
}
$others = 0
foreach ($o in @($owners.Keys | Sort-Object)) {
    $ports = (@($owners[$o]) | Sort-Object) -join ", "
    $proc = Get-Process -Id $o -ErrorAction SilentlyContinue
    $pname = "unknown"
    if ($null -ne $proc) { $pname = $proc.ProcessName }
    $cmdLine = ""
    try { $cmdLine = [string](Get-CimInstance Win32_Process -Filter ("ProcessId={0}" -f $o) -ErrorAction Stop).CommandLine } catch { }
    if ($pname -match '^pythonw?$') {
        Show-Detail @(("PID {0} ({1}) listens on {2}" -f $o, $pname, $ports), ("command line: " + $cmdLine))
        Fail $check ("python PID {0} already listens on port {1} and is not the app recorded in scripts\dev\demo\app.pid; a second twin app would evict the demo's model mid-demo. Close that app's window, or Stop-Process -Id {0} after confirming the command line above is a twin app (python app.py), then rerun" -f $o, $ports)
    }
    Say ("    WARNING port {0} is held by PID {1} ({2}), not a python app; the app will bind the next free port, so use the URL this script prints" -f $ports, $o, $pname)
    $others++
}
if ($others -gt 0) { Pass ("{0} ({1} non-python listener(s), see WARNING)" -f $check, $others) } else { Pass ("{0} (no listeners)" -f $check) }

# 3. free_gpu.ps1
$check = "free_gpu.ps1"
$fg = Invoke-Child "powershell" ("-NoProfile -ExecutionPolicy Bypass -File `"{0}`"" -f (Join-Path $root "scripts\free_gpu.ps1")) 180 "free_gpu"
Show-Detail ($fg.Out + $fg.Err) 30
if (-not $fg.Started) { Fail $check ("could not start powershell: {0}" -f ($fg.Err -join " ")) }
if ($fg.TimedOut) {
    Fail $check ("scripts\free_gpu.ps1 did not finish in 180 s (killed PID {0}); run it by hand to see where it hangs, then rerun" -f $fg.ProcId)
}
Pass ("{0} (exit {1})" -f $check, $fg.ExitCode)

# 4. GPU <= MaxGpuMiB (default 200 MiB; check_servers.ps1 parsing), retried for up to 20 s while models unload
$check = ("GPU <= {0} MiB" -f $MaxGpuMiB)
$used = -1
$gpu = $null
$deadline = (Get-Date).AddSeconds(20)
while ($true) {
    $gpu = $null
    try { $gpu = & nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu,display_active --format=csv,noheader } catch { $gpu = $null }
    $used = -1
    if ($gpu) {
        $first = ($gpu -split ",")[0].Trim()
        $num = ($first -replace "[^0-9]", "")
        if ($num) { $used = [int]$num }
    }
    if ($used -ge 0 -and $used -le $MaxGpuMiB) { break }
    if ((Get-Date) -ge $deadline) { break }
    Start-Sleep -Seconds 2
}
Show-Detail @("nvidia-smi (used, total, util, display_active): " + (@($gpu) -join " / "))
if ($used -lt 0) { Fail $check "could not read GPU memory from nvidia-smi; check the NVIDIA driver (nvidia-smi on PATH), then rerun" }
if ($used -gt $MaxGpuMiB) {
    $ps = Get-Body ($ollamaUrl + "/api/ps") 5
    $lm = Get-Body ($lmsUrl + "/api/v0/models") 5
    Show-Detail @("Ollama /api/ps: " + $ps.Text, "LM Studio /api/v0/models: " + $lm.Text) 5
    $suggest = 100 * [Math]::Ceiling(($used + 100) / 100)
    Fail $check ("GPU memory used {0} MiB > {1} MiB after free_gpu.ps1 and 20 s. If /api/ps or LM Studio above still shows a loaded model, rerun scripts\free_gpu.ps1; if another program holds the GPU, close it (never stop processes by name). If nothing is loaded and display_active above is Enabled (a projector or external screen on the NVIDIA GPU), the display holds that memory: rerun with -MaxGpuMiB {2}" -f $used, $MaxGpuMiB, $suggest)
}
Pass ("{0} ({1} MiB used)" -f $check, $used)

# 5. profile lint and index/digest fresh (read-only; never rebuilds)
$check = "profile lint and index/digest fresh"
$cp = Invoke-Child "python" "scripts\demo_rehearse.py --check-profile" 240 "check_profile"
Show-Detail $cp.Out 80
if ($cp.Err.Count -gt 0) { Write-Log "    --- check-profile stderr ---"; foreach ($l in $cp.Err) { Write-Log ("    " + $l) } }
if (-not $cp.Started) { Fail $check ("could not start python: {0}; check that python is on PATH" -f ($cp.Err -join " ")) }
if ($cp.TimedOut) { Fail $check ("demo_rehearse.py --check-profile did not finish in 240 s (killed PID {0}); run it by hand to see why" -f $cp.ProcId) }
if ($cp.ExitCode -ne 0) {
    $last = @($cp.Err | Where-Object { $_ -and $_.Trim() }) | Select-Object -Last 2
    Fail $check ("check-profile exit {0} (lint_issues, stale_indexes, stale_sources or digest_state above{1}); never rebuild before or during the demo (a rebuild writes data\ and loads models, and needs the owner's approval). Present the view-only beats only (Onboarding, Items, Eval, Status audit tail) and narrate every model beat from the DEMO.md Appendix: start the app by hand in a new window with Set-Location '{3}'; `$env:PYTHONUTF8='1'; python app.py --port {2} and never click a Rebuild button" -f $cp.ExitCode, $(if ($last) { "; stderr: " + ($last -join " | ") } else { "" }), $Port, $root)
}
$cpJson = ConvertFrom-JsonSafe ($cp.Out -join "`n")
$who = ""
if ($null -ne $cpJson) { $who = " for {0}, sha {1}" -f $cpJson.profile_name, ([string]$cpJson.profile_sha).Substring(0, [Math]::Min(12, ([string]$cpJson.profile_sha).Length)) }
Pass ("{0}{1}" -f $check, $who)

# 6. start the app in its own window and wait for HTTP 200
$check = "app HTTP 200"
$running = Get-LivePid $pidFile
if ($null -ne $running) {
    $oldPort = Read-PortFile
    $where = "(port unknown)"
    if ($oldPort -gt 0) { $where = "http://127.0.0.1:{0}/" -f $oldPort }
    Fail $check ("app already running at {0} (PID {1}, {2}); stop PID {1} or use it" -f $where, $running.Id, $running.ProcessName)
}
if (Test-Path -LiteralPath $portFile) { Remove-Item -LiteralPath $portFile -Force -ErrorAction SilentlyContinue }
if (Test-Path Env:TWIN_NO_WARM) { Remove-Item Env:TWIN_NO_WARM -ErrorAction SilentlyContinue }
$env:PYTHONUTF8 = "1"
$env:GRADIO_ANALYTICS_ENABLED = "False"
try {
    $app = Start-Process -FilePath "python" -ArgumentList ("app.py --port {0}" -f $Port) -WorkingDirectory $root -PassThru -ErrorAction Stop
} catch {
    Fail $check ("could not start python app.py: {0}; check that python is on PATH" -f $_.Exception.Message)
}
$null = $app.Handle
[System.IO.File]::WriteAllText($pidFile, [string]$app.Id, $utf8NoBom)
Say ("    started python app.py --port {0} in its own window: PID {1} (scripts\dev\demo\app.pid)" -f $Port, $app.Id)

$bound = 0
$deadline = (Get-Date).AddSeconds(120)
while ($true) {
    if ($app.HasExited) { break }
    $owners = @([int]$app.Id)
    try {
        $kids = @(Get-CimInstance Win32_Process -Filter ("ParentProcessId={0}" -f $app.Id) -ErrorAction Stop)
        foreach ($k in $kids) { $owners += [int]$k.ProcessId }
    } catch { }
    try {
        $conns = @(Get-NetTCPConnection -State Listen -ErrorAction Stop | Where-Object {
            $_.LocalPort -ge $Port -and $_.LocalPort -le ($Port + 9) -and ($owners -contains [int]$_.OwningProcess) })
        if ($conns.Count -gt 0) {
            $bound = [int](@($conns | Sort-Object LocalPort)[0].LocalPort)
            break
        }
    } catch { }
    if ((Get-Date) -ge $deadline) { break }
    Start-Sleep -Seconds 1
}
if ($app.HasExited) {
    Fail $check ("the app exited early with code {0}; to see the error, run Set-Location '{2}'; `$env:PYTHONUTF8='1'; python app.py --port {1} in a console (Ctrl+C if it starts), then rerun" -f $app.ExitCode, $Port, $root)
}
if ($bound -le 0) {
    Fail $check ("PID {0} is not listening on any port {1}..{2} after 120 s; look at the app window, stop PID {0}, then rerun" -f $app.Id, $Port, ($Port + 9))
}
[System.IO.File]::WriteAllText($portFile, [string]$bound, $utf8NoBom)
if ($bound -ne $Port) { Say ("    port {0} was busy; the app bound {1} (scripts\dev\demo\app.port)" -f $Port, $bound) }

$url = "http://127.0.0.1:{0}/" -f $bound
$code = ""
$deadline = (Get-Date).AddSeconds(60)
while ($true) {
    $code = Get-HttpCode $url 5
    if ($code -eq "200") { break }
    if ($app.HasExited) { break }
    if ((Get-Date) -ge $deadline) { break }
    Start-Sleep -Seconds 1
}
if ($code -ne "200") {
    if ($app.HasExited) {
        Fail $check ("the app exited with code {0} before answering {1}; to see the error, run Set-Location '{3}'; `$env:PYTHONUTF8='1'; python app.py --port {2} in a console (Ctrl+C if it starts), then rerun" -f $app.ExitCode, $url, $Port, $root)
    }
    Fail $check ("{0} answered HTTP '{1}' after 60 s (PID {2}); look at the app window, stop PID {2}, then rerun" -f $url, $code, $app.Id)
}
Pass ("{0} at {1} (PID {2})" -f $check, $url, $app.Id)
Say ("    open {0}; at T-5 run: powershell -NoProfile -ExecutionPolicy Bypass -File scripts\demo_prep.ps1 -WarmOnly" -f $url)
exit 0
