# PLAN_FINISH P5 Live driver (docs/PLAN_FINISH.md phase P5 = docs/PLAN_UNIFIED.md workflow D, stage 7).
# The only GPU driver of P5. The Claude Code PowerShell tool ends the processes a command started when that command
# returns, so the whole GPU sequence runs inside ONE background command and always cleans up after itself
# (pattern: scripts\dev\demo\resume\live_r2.ps1).
#   precheck: Ollama /api/ps has no models, nvidia-smi <= 200 MiB, no listener on 7861-7870 (else exit 2, nothing
#     started and nothing freed: never free a GPU someone else may be using)
#   1 back up data\items\twin_answers.json and scores.json to scripts\dev\finish\items_backup\ (SHA-256 recorded)
#   2 scripts\demo_prep.ps1 (cold), then -WarmOnly
#   3 python scripts\demo_rehearse.py --run <Run>; the Act draft is read from run<Run>_B5.2.txt
#   4 live checks on the app port (7861): See; Ask under demographic, persona, interview; pre-warm on tab select
#     (live_drive free_gpu, screenshot_tabs -Tabs act -VirtualTimeMs 40000, /api/ps); status strip vs the servers
#     (screenshot_tabs -Tabs status -VirtualTimeMs 20000, then /api/ps, lms ps, /api/v0/models). Each screenshot check
#     also gets a real-time capture with the DOM text (scripts\dev\finish\live_tab_text.py), because a virtual-time
#     shot shows the strip at its boot value and the pre-warm still pending (docs/EVIDENCE2.md notes).
#   5 python scripts\dev\finish\items_run_ui.py (/items_run interview, then /items_score); restore both items files
#     from the backup; confirm the scores SHA.
#   finally: stop the app PID this prep wrote to scripts\dev\demo\app.pid (python, owning the listener on the port in
#     app.port); restore the items files if they still differ from the backup; scripts\free_gpu.ps1; /api/ps,
#     nvidia-smi, the data\ list, data\act_answer.txt and the scores SHA -> scripts\dev\finish\cleanup_p5.txt.
# Evidence (never overwritten): scripts\dev\evidence\stage7_*.txt|.log|.json with <tag>.stderr.txt and
# <tag>.timing.json; shots in scripts\dev\evidence\stage7_shots\ and stage7_shots_cdp\; the rehearsal in
# scripts\dev\demo\rehearse_run<Run>.* and run<Run>_*; summary scripts\dev\finish\live_p5_summary.json; driver log
# scripts\dev\finish\live_p5.log.
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\dev\finish\live_p5.ps1 [-Run 12]
param([int]$Run = 12)
$ErrorActionPreference = "Continue"
$root = "C:\Users\Adity\Personal_digital_twin"
Set-Location -LiteralPath $root
$env:PYTHONUTF8 = "1"
$env:GRADIO_ANALYTICS_ENABLED = "False"
if (Test-Path Env:TWIN_NO_WARM) { Remove-Item Env:TWIN_NO_WARM -ErrorAction SilentlyContinue }
$demo = Join-Path $root "scripts\dev\demo"
$ev = Join-Path $root "scripts\dev\evidence"
$fin = Join-Path $root "scripts\dev\finish"
$log = Join-Path $fin "live_p5.log"
$pidFile = Join-Path $demo "app.pid"
$portFile = Join-Path $demo "app.port"
$backup = Join-Path $fin "items_backup"
$lms = Join-Path $env:LOCALAPPDATA "Programs\LM Studio\resources\app\.webpack\lms.exe"
$utf8 = New-Object System.Text.UTF8Encoding $false
$driverStart = Get-Date
$pinnedSha = "24D60CA6E76C16B3E04C5148028D9ABEA78D602D13FB7408F11C2565E6885DEF"
$itemFiles = @("twin_answers.json", "scores.json")
$question = "What did you learn from quitting the agency job?"
$ollamaPs = "http://127.0.0.1:11434/api/ps"
$lmsModels = "http://127.0.0.1:1234/api/v0/models"
$sum = [ordered]@{ run = $Run; started = $driverStart.ToString("o") }

# ---- helpers --------------------------------------------------------------------------------------------------------
function L([string]$t) {
    $line = "[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $t
    [System.IO.File]::AppendAllText($log, $line + "`r`n", $utf8)
    Write-Host $line
}
function Get-Url([string]$url) { return ((@(& curl.exe -s --max-time 5 $url) | Where-Object { $null -ne $_ }) -join "`n") }
function Get-HttpCode([string]$url) { return ((@(& curl.exe -s -o NUL -w "%{http_code}" --max-time 5 $url) -join "")).Trim() }
function Get-GpuLine { return (@(& nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu,display_active --format=csv,noheader) -join " / ") }
function Get-GpuMiB {
    $raw = (@(& nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits) -join "`n")
    $first = ($raw -split "`n")[0]
    $n = -1
    if ($null -ne $first -and [int]::TryParse($first.Trim(), [ref]$n)) { return $n }
    return -1
}
function Get-State {
    $ps = Get-Url $ollamaPs
    $lmsText = Get-Url $lmsModels
    $loaded = "LM Studio no JSON"
    try { $loaded = "LM Studio loaded: [" + ((@(($lmsText | ConvertFrom-Json).data | Where-Object { $_.state -eq "loaded" } | ForEach-Object { $_.id })) -join ", ") + "]" } catch { }
    return ("/api/ps {0} | nvidia-smi {1} | {2}" -f $ps, (Get-GpuLine), $loaded)
}
function Get-Listeners([int]$lo, [int]$hi) {
    return @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -ge $lo -and $_.LocalPort -le $hi })
}
function Sha([string]$p) {
    if (Test-Path -LiteralPath $p) { return (Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash }
    return "missing"
}
function Save-Text([string]$path, [string]$text) {
    if (Test-Path -LiteralPath $path) { L ("refusing to overwrite {0}" -f $path); return $false }
    [System.IO.File]::WriteAllText($path, $text, $utf8)
    return $true
}
function Save-Url([string]$name, [string]$url) {
    $t = Get-Url $url
    $null = Save-Text (Join-Path $ev $name) $t
    L ("saved scripts\dev\evidence\{0} ({1} chars)" -f $name, $t.Length)
    return $t
}
function Save-LmsPs([string]$name) {
    $out = Join-Path $ev $name
    $err = Join-Path $ev ($name -replace '\.txt$', '.stderr.txt')
    if (Test-Path -LiteralPath $out) { L ("refusing to overwrite {0}" -f $out); return "" }
    $p = Start-Process -FilePath $lms -ArgumentList "ps" -WorkingDirectory $root -NoNewWindow -PassThru `
        -RedirectStandardOutput $out -RedirectStandardError $err
    $null = $p.Handle
    $code = -1
    if (-not $p.WaitForExit(60000)) { try { $p.Kill() } catch { }; L "lms ps did not return in 60 s (killed)" } else { $p.WaitForExit(); $code = $p.ExitCode }
    $t = ""
    try { $t = Get-Content -LiteralPath $out -Raw -Encoding UTF8 } catch { }
    L ("saved scripts\dev\evidence\{0} (lms ps exit {1})" -f $name, $code)
    return $t
}
function Run-Step([string]$dir, [string]$tag, [string]$file, [string]$argString, [int]$timeoutSec, [string]$outName = "") {
    if (-not $outName) { $outName = "$tag.log" }
    $out = Join-Path $dir $outName
    $err = Join-Path $dir ("{0}.stderr.txt" -f $tag)
    $tim = Join-Path $dir ("{0}.timing.json" -f $tag)
    if ((Test-Path -LiteralPath $out) -or (Test-Path -LiteralPath $tim)) { L ("refusing to overwrite {0}" -f $out); return 99 }
    L ("> {0} {1}" -f $file, $argString)
    $t0 = Get-Date
    $p = Start-Process -FilePath $file -ArgumentList $argString -WorkingDirectory $root -NoNewWindow -PassThru `
        -RedirectStandardOutput $out -RedirectStandardError $err
    $null = $p.Handle
    $timedOut = $false
    if (-not $p.WaitForExit($timeoutSec * 1000)) {
        $timedOut = $true
        try { $p.Kill() } catch { }
        $null = $p.WaitForExit(10000)
    }
    $t1 = Get-Date
    $code = -1
    if (-not $timedOut) { $p.WaitForExit(); $code = $p.ExitCode }
    $rec = [ordered]@{ tag = $tag; command = "$file $argString"; child_pid = $p.Id; started = $t0.ToString("o");
                       ended = $t1.ToString("o"); wall_ms = [int]($t1 - $t0).TotalMilliseconds; exit_code = $code;
                       timed_out = $timedOut; timeout_s = $timeoutSec; output = $outName }
    [System.IO.File]::WriteAllText($tim, ($rec | ConvertTo-Json), $utf8)
    $suffix = ""
    if ($timedOut) { $suffix = " (TIMED OUT, child killed)" }
    L ("< {0}: exit {1}, {2} ms{3}" -f $tag, $code, $rec.wall_ms, $suffix)
    return $code
}
function Show-Lines([string]$path, [string]$pattern, [int]$max = 60) {
    if (-not (Test-Path -LiteralPath $path)) { L ("    (no {0})" -f $path); return }
    $n = 0
    foreach ($ln in (Get-Content -LiteralPath $path -Encoding UTF8)) {
        if ($ln -match $pattern) {
            $s = [string]$ln
            if ($s.Length -gt 400) { $s = $s.Substring(0, 400) + " ..." }
            L ("    " + $s)
            $n++
            if ($n -ge $max) { L "    ..."; break }
        }
    }
}
# Lines between "=== <label> ===" and the next "=== " header (demo_rehearse prefixes headers with "[+x s] ").
function Get-Block([string]$path, [string]$label) {
    $lines = New-Object System.Collections.Generic.List[string]
    if (-not (Test-Path -LiteralPath $path)) { return $lines.ToArray() }
    $in = $false
    foreach ($ln in (Get-Content -LiteralPath $path -Encoding UTF8)) {
        if ($ln -match ('=== ' + [regex]::Escape($label) + ' ===')) { $in = $true; continue }
        if ($in -and $ln -match '^(\[\+[0-9.]+ s\] )?=== ') { break }
        if ($in -and $ln -notmatch '^# ') { $lines.Add([string]$ln) }
    }
    return $lines.ToArray()
}
function Get-OwnAppPid {
    if ((Test-Path -LiteralPath $pidFile) -and (Get-Item -LiteralPath $pidFile).LastWriteTime -gt $driverStart) {
        $n = 0
        if ([int]::TryParse(([string](Get-Content -LiteralPath $pidFile -TotalCount 1)).Trim(), [ref]$n)) { return $n }
    }
    return 0
}
function Read-Port {
    $n = 0
    if (Test-Path -LiteralPath $portFile) { [void][int]::TryParse(([string](Get-Content -LiteralPath $portFile -TotalCount 1)).Trim(), [ref]$n) }
    if ($n -le 0) { $n = 7861 }
    return $n
}
function Restore-Items([string]$why) {
    $lines = New-Object System.Collections.Generic.List[string]
    foreach ($f in $itemFiles) {
        $src = Join-Path $backup $f
        $dst = Join-Path $root ("data\items\" + $f)
        $b = Sha $src
        $d = Sha $dst
        if ($b -ne $d) {
            Copy-Item -LiteralPath $src -Destination $dst -Force
            $d2 = Sha $dst
            $verdict = "STILL DIFFERS"
            if ($d2 -eq $b) { $verdict = "equals the backup" }
            $lines.Add(("{0}: data SHA-256 {1} differed from the backup {2}; copied the backup back ({3}); now {4} ({5})" -f $f, $d, $b, $why, $d2, $verdict))
        } else {
            $lines.Add(("{0}: data SHA-256 {1} equals the backup; nothing to restore ({2})" -f $f, $d, $why))
        }
    }
    return $lines.ToArray()
}
function Write-Summary {
    $p = Join-Path $fin "live_p5_summary.json"
    if (Test-Path -LiteralPath $p) { $p = Join-Path $fin ("live_p5_summary_{0}.json" -f (Get-Date -Format "yyyyMMdd-HHmmss")) }
    $sum.ended = (Get-Date).ToString("o")
    [System.IO.File]::WriteAllText($p, ($sum | ConvertTo-Json -Depth 6), $utf8)
    L ("summary: " + $p)
}

# ---- precheck (touches nothing) -------------------------------------------------------------------------------------
L ("=== live_p5 start: Run={0}, driver PID {1}" -f $Run, $PID)
$pre = Get-Url $ollamaPs
$preGpu = Get-GpuMiB
$preListen = @(Get-Listeners 7861 7870)
L ("precheck: /api/ps {0} | nvidia-smi {1} | used {2} MiB | listeners on 7861-7870: {3} | python processes: {4}" -f $pre, (Get-GpuLine), $preGpu, $preListen.Count, @(Get-Process python -ErrorAction SilentlyContinue).Count)
if (($pre -notmatch '"models":\[\]') -or $preGpu -lt 0 -or $preGpu -gt 200 -or $preListen.Count -gt 0) {
    L "BLOCKED: the GPU is not idle or a listener holds 7861-7870; nothing was started and nothing was freed"
    $sum.blocked = "precheck: $pre, $preGpu MiB, $($preListen.Count) listeners"
    Write-Summary
    exit 2
}

# ---- 1 items backup -------------------------------------------------------------------------------------------------
New-Item -ItemType Directory -Force $backup | Out-Null
$bk = New-Object System.Collections.Generic.List[string]
$bk.Add(("items backup {0}" -f (Get-Date -Format o)))
$backupOk = $true
foreach ($f in $itemFiles) {
    $src = Join-Path $root ("data\items\" + $f)
    $dst = Join-Path $backup $f
    $s = Sha $src
    if (Test-Path -LiteralPath $dst) {
        $d = Sha $dst
        if ($d -eq $s) { $bk.Add(("{0}: backup already present and equal to data\items\{0}, kept: {1}" -f $f, $d)) }
        else { $bk.Add(("{0}: backup present but DIFFERS (data {1}, backup {2}): refusing to continue" -f $f, $s, $d)); $backupOk = $false }
    } else {
        Copy-Item -LiteralPath $src -Destination $dst
        $d = Sha $dst
        $eq = "DIFFERENT"
        if ($d -eq $s) { $eq = "equal" }
        $bk.Add(("{0}: copied data\items\{0} -> scripts\dev\finish\items_backup\{0}; SHA-256 data {1}, backup {2} ({3})" -f $f, $s, $d, $eq))
        if ($d -ne $s) { $backupOk = $false }
    }
    $sum[("sha_before_" + $f)] = $s
}
$scoresNow = Sha (Join-Path $root "data\items\scores.json")
$pinnedWord = "DIFFERS FROM"
if ($scoresNow -eq $pinnedSha) { $pinnedWord = "equals" }
$bk.Add(("data\items\scores.json SHA-256 {0} ({1} the pinned value)" -f $scoresNow, $pinnedWord))
if ($scoresNow -ne $pinnedSha) { $backupOk = $false }
$shaFile = Join-Path $backup "sha256.txt"
if (-not (Test-Path -LiteralPath $shaFile)) { [System.IO.File]::WriteAllText($shaFile, (($bk -join "`r`n") + "`r`n"), $utf8) }
foreach ($line in $bk) { L ("backup| " + $line) }
if (-not $backupOk) {
    L "BLOCKED: the items backup or the scores SHA check failed; nothing was started"
    $sum.blocked = "items backup"
    Write-Summary
    exit 3
}

$appPid = 0
$appPort = 7861
try {
    # ---- 2 cold prep, then -WarmOnly --------------------------------------------------------------------------------
    $rc = Run-Step $ev "stage7_prep_cold" "powershell" "-NoProfile -ExecutionPolicy Bypass -File scripts\demo_prep.ps1" 900
    $sum.prep_cold_exit = $rc
    Show-Lines (Join-Path $ev "stage7_prep_cold.log") '^(PASS|FAIL)|WARNING|note:|started python|was busy'
    $appPid = Get-OwnAppPid
    if ($rc -ne 0) { throw ("cold prep exit {0}" -f $rc) }
    $appPort = Read-Port
    L ("app PID written by this prep: {0}; app.port {1}" -f $appPid, $appPort)
    if ($appPort -ne 7861) { L ("WARNING the app bound port {0}, not 7861" -f $appPort) }
    $rc = Run-Step $ev "stage7_prep_warm" "powershell" "-NoProfile -ExecutionPolicy Bypass -File scripts\demo_prep.ps1 -WarmOnly" 600
    $sum.prep_warm_exit = $rc
    Show-Lines (Join-Path $ev "stage7_prep_warm.log") '^(PASS|FAIL)|keep-alive'
    if ($rc -ne 0) { throw ("-WarmOnly exit {0}" -f $rc) }
    L ("after prep: " + (Get-State))

    # ---- 3 full rehearsal ------------------------------------------------------------------------------------------
    $rc = Run-Step $demo ("rehearse_run{0}" -f $Run) "python" ("scripts\demo_rehearse.py --run {0}" -f $Run) 1800
    $sum.rehearsal_exit = $rc
    Show-Lines (Join-Path $demo ("rehearse_run{0}.log" -f $Run)) '^\[run|^ERROR|^WARNING'
    $b52 = Join-Path $demo ("run{0}_B5.2.txt" -f $Run)
    $ans = @(Get-Block $b52 "answer" | Where-Object { $_.Trim() })
    $ansText = ($ans -join " ").Trim()
    $isDraft = ($ansText.Length -gt 0) -and ($ansText -notmatch '(?i)ran out of steps') -and ($ansText -notmatch 'search_profile|draft_message')
    foreach ($ansLine in $ans) { L ("    B5.2 answer| " + $ansLine) }
    $draftWord = "NO"
    if ($isDraft) { $draftWord = "yes (message text, not the step-limit reply)" }
    L ("ACT DRAFT run{0}_B5.2: {1}; {2} chars" -f $Run, $draftWord, $ansText.Length)
    $sum.act_draft = $isDraft
    $sum.act_answer = $ansText
    $sj = Join-Path $demo ("run{0}_summary.json" -f $Run)
    if (Test-Path -LiteralPath $sj) {
        try {
            $sjson = Get-Content -LiteralPath $sj -Raw -Encoding UTF8 | ConvertFrom-Json
            $sum.rehearsal = [ordered]@{ steps = $sjson.steps; ok = $sjson.ok_count; expect_ok = $sjson.expect_ok_count;
                                         total_ms = $sjson.total_ms; failed = @($sjson.failed_steps);
                                         expect_failed = @($sjson.expect_failed_steps); over_budget = @($sjson.over_budget_steps);
                                         scores_unchanged = $sjson.scores_unchanged }
            L ("rehearsal summary: " + ($sum.rehearsal | ConvertTo-Json -Compress))
        } catch { L ("could not parse " + $sj) }
    }
    L ("after rehearsal: " + (Get-State))
    $code = Get-HttpCode ("http://127.0.0.1:{0}/" -f $appPort)
    if ($code -ne "200") { throw ("the app on port {0} answered HTTP '{1}' after the rehearsal" -f $appPort, $code) }

    # ---- 4a See ------------------------------------------------------------------------------------------------------
    $rc = Run-Step $ev "stage7_see" "python" ("scripts\dev\live_drive.py see scripts\dev\test_photo.jpg --port {0}" -f $appPort) 600 "stage7_see.txt"
    $sum.see_exit = $rc
    Show-Lines (Join-Path $ev "stage7_see.txt") '.' 40
    $null = Save-Url "stage7_see_api_ps.json" $ollamaPs
    $null = Save-Url "stage7_see_lms_models.json" $lmsModels

    # ---- 4b three-condition Ask --------------------------------------------------------------------------------------
    $askRes = [ordered]@{}
    foreach ($cond in @("demographic", "persona", "interview")) {
        $tag = "stage7_ask_{0}" -f $cond
        $argStr = 'scripts\dev\live_drive.py ask "{0}" --condition {1} --port {2}' -f $question, $cond, $appPort
        $rc = Run-Step $ev $tag "python" $argStr 600 ($tag + ".txt")
        $af = Join-Path $ev ($tag + ".txt")
        $trace = @(Get-Block $af "trace_md")
        foreach ($tl in $trace) { if ($tl.Trim()) { L ("    trace| " + $tl) } }
        $reply = (@(Get-Block $af "reply_text") -join " ").Trim()
        if ($reply.Length -gt 400) { $reply = $reply.Substring(0, 400) + " ..." }
        L ("    reply| " + $reply)
        $traceText = $trace -join "`n"
        $okAsk = $false
        $detail = ""
        if ($cond -eq "demographic") {
            $detail = "condition: demographic (chunks: 0, digest: no)"
            $okAsk = $traceText.Contains($detail)
        } elseif ($cond -eq "persona") {
            $detail = "condition: persona (chunks: 0, digest: yes)"
            $okAsk = $traceText.Contains($detail)
        } else {
            $rl = @($trace | Where-Object { $_ -match 'retrieval\[' }) | Select-Object -First 1
            $ids = @()
            if ($rl) {
                $body = ([string]$rl -replace '^.*?k=\d+:\s*', '') -replace '\s*\([0-9.]+ s\)\s*$', ''
                $ids = @($body -split ',\s+' | Where-Object { $_ -match '\s\d\.\d+$' } | ForEach-Object { ($_ -replace '\s\d\.\d+$', '').Trim() })
            }
            $okAsk = ($ids.Count -eq 5)
            $detail = ("{0} chunk ids: {1}" -f $ids.Count, ($ids -join ", "))
        }
        $verdictAsk = "FAIL"
        if ($okAsk -and $rc -eq 0) { $verdictAsk = "PASS" }
        L ("{0} Ask {1}: exit {2}; {3}" -f $verdictAsk, $cond, $rc, $detail)
        $askRes[$cond] = [ordered]@{ exit = $rc; ok = $okAsk; detail = $detail }
    }
    $sum.ask = $askRes
    $null = Save-Url "stage7_ask_api_ps.json" $ollamaPs
    $null = Save-Url "stage7_ask_lms_models.json" $lmsModels

    # ---- 4c pre-warm on tab select -----------------------------------------------------------------------------------
    $rc = Run-Step $ev "stage7_prewarm_free_gpu" "python" ("scripts\dev\live_drive.py free_gpu --port {0}" -f $appPort) 300 "stage7_prewarm_free_gpu.txt"
    Start-Sleep -Seconds 3
    $null = Save-Url "stage7_prewarm_api_ps_before.json" $ollamaPs
    $null = Save-Url "stage7_prewarm_lms_models_before.json" $lmsModels
    L ("before the act shot: " + (Get-State))
    $shotAct = Join-Path $ev "stage7_shots\light_1440_act.png"
    if (Test-Path -LiteralPath $shotAct) { L ("refusing to overwrite " + $shotAct) } else {
        $rc = Run-Step $ev "stage7_prewarm_shot" "powershell" ("-NoProfile -ExecutionPolicy Bypass -File scripts\screenshot_tabs.ps1 -Port {0} -Tabs act -VirtualTimeMs 40000 -OutDir scripts\dev\evidence\stage7_shots" -f $appPort) 300 "stage7_prewarm_shot.txt"
    }
    $pw = Save-Url "stage7_prewarm_api_ps.json" $ollamaPs
    $null = Save-Url "stage7_prewarm_lms_models.json" $lmsModels
    $null = Save-Text (Join-Path $ev "stage7_prewarm_nvidia_smi.txt") ((Get-GpuLine) + "`r`n")
    $hermes = ($pw -match 'hermes3:8b')
    L ("pre-warm on tab select (virtual-time shot): hermes3:8b in /api/ps right after the shot: {0}" -f $hermes)
    $sum.prewarm_hermes_after_shot = $hermes
    if (-not $hermes) {
        $deadline = (Get-Date).AddSeconds(90)
        while ((Get-Date) -lt $deadline) {
            Start-Sleep -Seconds 3
            $tp = Get-Url $ollamaPs
            if ($tp -match 'hermes3:8b') {
                $null = Save-Text (Join-Path $ev "stage7_prewarm_api_ps_poll.json") $tp
                L "hermes3:8b appeared in /api/ps (saved stage7_prewarm_api_ps_poll.json)"
                break
            }
        }
    }
    # real-time capture from cold: free the GPU again, open ?tab=act and read the gpu note as it changes
    $rc = Run-Step $ev "stage7_prewarm_free_gpu_2" "python" ("scripts\dev\live_drive.py free_gpu --port {0}" -f $appPort) 300 "stage7_prewarm_free_gpu_2.txt"
    Start-Sleep -Seconds 3
    $null = Save-Url "stage7_prewarm_cdp_api_ps_before.json" $ollamaPs
    $rc = Run-Step $ev "stage7_prewarm_cdp" "python" "scripts\dev\finish\live_tab_text.py --tab act --wait 90 --out-dir scripts\dev\evidence\stage7_shots_cdp --json scripts\dev\evidence\stage7_prewarm_cdp.json" 240 "stage7_prewarm_cdp.txt"
    Show-Lines (Join-Path $ev "stage7_prewarm_cdp.txt") '.' 30
    $pw2 = Save-Url "stage7_prewarm_cdp_api_ps.json" $ollamaPs
    $null = Save-Url "stage7_prewarm_cdp_lms_models.json" $lmsModels
    $sum.prewarm_hermes_after_cdp = ($pw2 -match 'hermes3:8b')
    L ("real-time capture: hermes3:8b in /api/ps afterwards: {0}" -f $sum.prewarm_hermes_after_cdp)

    # ---- 4d status strip vs the servers ------------------------------------------------------------------------------
    L ("before the status shot: " + (Get-State))
    $shotSt = Join-Path $ev "stage7_shots\light_1440_status.png"
    if (Test-Path -LiteralPath $shotSt) { L ("refusing to overwrite " + $shotSt) } else {
        $rc = Run-Step $ev "stage7_strip_shot" "powershell" ("-NoProfile -ExecutionPolicy Bypass -File scripts\screenshot_tabs.ps1 -Port {0} -Tabs status -VirtualTimeMs 20000 -OutDir scripts\dev\evidence\stage7_shots" -f $appPort) 300 "stage7_strip_shot.txt"
    }
    $null = Save-Url "stage7_strip_api_ps.json" $ollamaPs
    $null = Save-LmsPs "stage7_strip_lms_ps.txt"
    $null = Save-Url "stage7_strip_lms_models.json" $lmsModels
    $null = Save-Text (Join-Path $ev "stage7_strip_nvidia_smi.txt") ((Get-GpuLine) + "`r`n")
    $rc = Run-Step $ev "stage7_strip_cdp" "python" "scripts\dev\finish\live_tab_text.py --tab status --wait 12 --out-dir scripts\dev\evidence\stage7_shots_cdp --json scripts\dev\evidence\stage7_strip_cdp.json" 240 "stage7_strip_cdp.txt"
    $null = Save-Url "stage7_strip_cdp_api_ps.json" $ollamaPs
    $null = Save-LmsPs "stage7_strip_cdp_lms_ps.txt"
    $null = Save-Url "stage7_strip_cdp_lms_models.json" $lmsModels
    $null = Save-Text (Join-Path $ev "stage7_strip_cdp_nvidia_smi.txt") ((Get-GpuLine) + "`r`n")
    Show-Lines (Join-Path $ev "stage7_strip_cdp.txt") '.' 40
    $rc = Run-Step $ev "stage7_strip_status_api" "python" ("scripts\dev\live_drive.py status --port {0}" -f $appPort) 120 "stage7_strip_status_api.txt"
    L ("after the strip checks: " + (Get-State))

    # ---- 5 items through the UI, then restore ------------------------------------------------------------------------
    L ("before items: " + (Get-State))
    $rc = Run-Step $ev "stage7_items_ui" "python" ("scripts\dev\finish\items_run_ui.py --port {0} --condition interview" -f $appPort) 3600 "stage7_items_ui.txt"
    $sum.items_ui_exit = $rc
    Show-Lines (Join-Path $ev "stage7_items_ui.txt") '^=== |elapsed|model calls|Decision|twin_answers\.json|scores\.json|"rows' 80
    $rlines = New-Object System.Collections.Generic.List[string]
    $rlines.Add(("items restore {0}" -f (Get-Date -Format o)))
    foreach ($x in @(Restore-Items "stage 7.7 restore after /items_run and /items_score")) { $rlines.Add($x) }
    $scAfter = Sha (Join-Path $root "data\items\scores.json")
    $scWord = "DIFFERS FROM"
    if ($scAfter -eq $pinnedSha) { $scWord = "equals" }
    $rlines.Add(("data\items\scores.json SHA-256 after the restore: {0} ({1} the pinned {2})" -f $scAfter, $scWord, $pinnedSha))
    $null = Save-Text (Join-Path $ev "stage7_items_restore.txt") (($rlines -join "`r`n") + "`r`n")
    foreach ($x in $rlines) { L ("restore| " + $x) }
    $sum.items_restored_in_step = ($scAfter -eq $pinnedSha)
    L ("after items: " + (Get-State))
} catch {
    L ("STOPPED: " + $_.Exception.Message)
    $sum.stopped = $_.Exception.Message
} finally {
    $c = New-Object System.Collections.Generic.List[string]
    $c.Add(("cleanup (P5 Live, scripts\dev\finish\live_p5.ps1, run {0}) {1}" -f $Run, (Get-Date -Format o)))
    $c.Add(("before cleanup: " + (Get-State)))
    if ($appPid -le 0) { $appPid = Get-OwnAppPid }
    $recPort = Read-Port
    $stopped = $false
    if ($appPid -gt 0) {
        $proc = Get-Process -Id $appPid -ErrorAction SilentlyContinue
        if ($null -ne $proc -and $proc.ProcessName -match '^pythonw?$') {
            $owners = @(Get-NetTCPConnection -State Listen -LocalPort $recPort -ErrorAction SilentlyContinue | ForEach-Object { [int]$_.OwningProcess } | Sort-Object -Unique)
            $kids = @()
            try { $kids = @(Get-CimInstance Win32_Process -Filter ("ParentProcessId={0}" -f $appPid) -ErrorAction Stop | ForEach-Object { [int]$_.ProcessId }) } catch { }
            $ownerIsApp = ($owners -contains $appPid)
            $kidOwners = @($owners | Where-Object { $kids -contains $_ })
            $startedHere = $false
            $startText = "?"
            try { $startedHere = ($proc.StartTime -ge $driverStart); $startText = $proc.StartTime.ToString("s") } catch { }
            $c.Add(("app.pid = {0} (written by this prep at {1}); process {2} started {3}; listeners on app.port {4}: [{5}]; the app PID owns it: {6}; python child owners: [{7}]; started after this driver began: {8}" -f $appPid, (Get-Item -LiteralPath $pidFile).LastWriteTime.ToString("s"), $proc.ProcessName, $startText, $recPort, ($owners -join ", "), $ownerIsApp, ($kidOwners -join ", "), $startedHere))
            if ($ownerIsApp -or $kidOwners.Count -gt 0 -or $startedHere) {
                foreach ($k in $kidOwners) {
                    $kp = Get-Process -Id $k -ErrorAction SilentlyContinue
                    if ($null -ne $kp -and $kp.ProcessName -match '^pythonw?$') { Stop-Process -Id $k -ErrorAction SilentlyContinue; $c.Add(("Stop-Process -Id {0} (python child that owned the listener)" -f $k)) }
                }
                Stop-Process -Id $appPid -ErrorAction SilentlyContinue
                Start-Sleep -Seconds 3
                if (Get-Process -Id $appPid -ErrorAction SilentlyContinue) {
                    Stop-Process -Id $appPid -Force -ErrorAction SilentlyContinue
                    Start-Sleep -Seconds 2
                    $c.Add("still alive after 3 s: Stop-Process -Force")
                }
                $alive = [bool](Get-Process -Id $appPid -ErrorAction SilentlyContinue)
                $c.Add(("Stop-Process -Id {0}; still alive afterwards: {1}" -f $appPid, $alive))
                if (-not $alive) {
                    $stopped = $true
                    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
                    $c.Add(("removed scripts\dev\demo\app.pid (stopped PID {0}), so a reused PID can never be named later" -f $appPid))
                }
            } else {
                $c.Add(("PID {0} is python but neither owns the listener on {1} nor started after this driver began: NOT stopped" -f $appPid, $recPort))
            }
        } else {
            $c.Add(("app.pid = {0}: not a live python process, nothing stopped" -f $appPid))
        }
    } else {
        $c.Add("no app PID was written by this prep: nothing stopped")
    }
    $sum.app_pid = $appPid
    $sum.app_pid_stopped = $stopped
    $c.Add(("listeners on 7861-7870 after the stop: {0}" -f @(Get-Listeners 7861 7870).Count))
    if ((Test-Path -LiteralPath (Join-Path $backup "scores.json")) -and (Test-Path -LiteralPath (Join-Path $backup "twin_answers.json"))) {
        foreach ($x in @(Restore-Items "cleanup check after the app stopped")) { $c.Add($x) }
    } else {
        $c.Add("no complete items backup in scripts\dev\finish\items_backup: nothing to compare")
    }
    $fgTag = "stage7_free_gpu"
    if (Test-Path -LiteralPath (Join-Path $ev "stage7_free_gpu.txt")) { $fgTag = "stage7_free_gpu_{0}" -f (Get-Date -Format "yyyyMMdd-HHmmss") }
    $rcFree = Run-Step $ev $fgTag "powershell" "-NoProfile -ExecutionPolicy Bypass -File scripts\free_gpu.ps1" 300 ($fgTag + ".txt")
    $c.Add(("scripts\free_gpu.ps1 exit {0} (output: scripts\dev\evidence\{1}.txt)" -f $rcFree, $fgTag))
    $psAfter = ""
    $mib = -1
    $deadline = (Get-Date).AddSeconds(30)
    while ($true) {
        $psAfter = Get-Url $ollamaPs
        $mib = Get-GpuMiB
        if (($psAfter -match '"models":\[\]') -and $mib -ge 0 -and $mib -le 200) { break }
        if ((Get-Date) -ge $deadline) { break }
        Start-Sleep -Seconds 2
    }
    $c.Add(("after: " + (Get-State)))
    $c.Add(("Ollama /api/ps body: {0}" -f $psAfter))
    $gpuWord = "ABOVE"
    if ($mib -ge 0 -and $mib -le 200) { $gpuWord = "<=" }
    $c.Add(("nvidia-smi memory.used: {0} MiB ({1} 200 MiB)" -f $mib, $gpuWord))
    $sum.api_ps_after = $psAfter
    $sum.gpu_mib_after = $mib
    $sum.gpu_freed = (($psAfter -match '"models":\[\]') -and $mib -ge 0 -and $mib -le 200)
    $shaAfter = Sha (Join-Path $root "data\items\scores.json")
    $shaWord = "DIFFERS FROM"
    if ($shaAfter -eq $pinnedSha) { $shaWord = "equals" }
    $c.Add(("data\items\scores.json SHA-256 {0} ({1} the pinned value)" -f $shaAfter, $shaWord))
    $ta = Sha (Join-Path $root "data\items\twin_answers.json")
    $tb = Sha (Join-Path $backup "twin_answers.json")
    $taWord = "DIFFERS FROM"
    if ($ta -eq $tb) { $taWord = "equals" }
    $c.Add(("data\items\twin_answers.json SHA-256 {0} ({1} the backup {2})" -f $ta, $taWord, $tb))
    $sum.scores_sha_after = $shaAfter
    $sum.items_restored = (($shaAfter -eq $pinnedSha) -and ($ta -eq $tb))
    $actPresent = Test-Path -LiteralPath (Join-Path $root "data\act_answer.txt")
    $c.Add(("data\act_answer.txt present: {0}" -f $actPresent))
    $nowFiles = @(Get-ChildItem -LiteralPath (Join-Path $root "data") -Recurse -File | ForEach-Object { $_.FullName.Substring($root.Length + 1) })
    $beforeFiles = @(Get-Content -LiteralPath (Join-Path $demo "data_files_before.txt") -Encoding UTF8 | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    $added = @($nowFiles | Where-Object { $beforeFiles -notcontains $_ })
    $gone = @($beforeFiles | Where-Object { $nowFiles -notcontains $_ })
    $c.Add(("data\ files: {0} now, {1} in data_files_before.txt; added [{2}]; missing [{3}]" -f $nowFiles.Count, $beforeFiles.Count, ($added -join ", "), ($gone -join ", ")))
    $sum.data_files_match = ($added.Count -eq 0 -and $gone.Count -eq 0)
    $sum.act_answer_absent = (-not $actPresent)
    $c.Add(("python processes: {0}; listeners on 7861-7880: {1}" -f @(Get-Process python -ErrorAction SilentlyContinue).Count, @(Get-Listeners 7861 7880).Count))
    $cp = Join-Path $fin "cleanup_p5.txt"
    if (Test-Path -LiteralPath $cp) { $cp = Join-Path $fin ("cleanup_p5_{0}.txt" -f (Get-Date -Format "yyyyMMdd-HHmmss")) }
    [System.IO.File]::WriteAllText($cp, (($c -join "`r`n") + "`r`n"), $utf8)
    foreach ($line in $c) { L ("cleanup| " + $line) }
    $sum.cleanup = $cp
    Write-Summary
    L "=== live_p5 end"
}
