# Capture one headless-Chrome screenshot per tab of the running app (default http://127.0.0.1:7861).
# Requires the ?tab= deep link (twin/ui/frame.py). Output: <OutDir>\<Theme>_<Width>_<tab>.png
#   powershell -File scripts\screenshot_tabs.ps1 -Port 7871 -Theme dark -Width 400 -Tabs ask,status
# Note: opening a tab via ?tab= fires its pre-warm (model load) unless the app runs with TWIN_NO_WARM=1, so
# either boot the app with the switch (UI work) or give big-model tabs a budget of 30-40 s.
# Note (2026-09-14): a Chrome --headless=new window can't be narrower than 500 px, so -Width 400 lays the page out at
# 500 px and crops the PNG to 400 (innerWidth reads 500). For a true 400 px viewport and a scrollWidth measurement use
# python scripts\dev\finish\cdp_shot.py (DevTools device-metrics emulation), which scripts\dev\finish\ui_check.ps1 uses.
param(
    [int]$Port = 7861,
    [ValidateSet("light", "dark")][string]$Theme = "light",
    [int]$Width = 1440,          # 1440 (desktop) or 400 (phone)
    [string[]]$Tabs = @("onboarding", "ask", "decide", "act", "see", "items", "eval", "status"),
    [int]$VirtualTimeMs = 20000,
    [string]$OutDir = "scripts\dev\shots"
)
$chrome = "$env:ProgramFiles\Google\Chrome\Application\chrome.exe"
if (-not (Test-Path $chrome)) { $chrome = "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe" }
if (-not (Test-Path $chrome)) { Write-Host "no chrome.exe / msedge.exe found"; exit 1 }
New-Item -ItemType Directory -Force $OutDir | Out-Null
# One Chrome profile per port so parallel agents on different ports never share a user-data-dir.
$profileDir = Join-Path $env:TEMP "twin_headless_$Port"
$height = if ($Width -le 400) { 900 } else { 1000 }
$baseUrl = "http://127.0.0.1:$Port"
# "-Tabs act,see,eval" arrives as one string when invoked with powershell -File; split it.
$Tabs = @($Tabs | ForEach-Object { $_ -split "," } | ForEach-Object { $_.Trim() } | Where-Object { $_ })
foreach ($tab in $Tabs) {
    $out = Join-Path (Resolve-Path $OutDir) ("{0}_{1}_{2}.png" -f $Theme, $Width, $tab)
    if (Test-Path $out) { Remove-Item $out -Force }
    # nomotion=1: the page-load JS (twin/ui/frame.py TAB_JS) disables CSS transitions, so the sidebar (status
    # strip) and its content push are captured in their final state; the virtual-time budget alone fires the
    # shot while they are still sliding in. --run-all-compositor-stages-before-draw keeps the frame deterministic.
    $url = "$baseUrl/?tab=$tab&__theme=$Theme&nomotion=1"
    $args = @(
        "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run", "--no-default-browser-check",
        "--run-all-compositor-stages-before-draw",
        "--user-data-dir=$profileDir", "--window-size=$Width,$height",
        "--virtual-time-budget=$VirtualTimeMs", "--timeout=$($VirtualTimeMs + 5000)",
        "--screenshot=$out", $url
    )
    $p = Start-Process -FilePath $chrome -ArgumentList $args -PassThru -WindowStyle Hidden
    if (-not $p.WaitForExit(60000)) { $p.Kill(); Write-Host "$tab : chrome timed out" }
    if (Test-Path $out) { Write-Host ("{0,-10} {1,8} bytes  {2}" -f $tab, (Get-Item $out).Length, $out) } else { Write-Host "$tab : no screenshot written" }
}
