# Free the GPU: stop every Ollama model and unload everything in LM Studio.
$ErrorActionPreference = "Continue"
$ollama = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe"
$lms = "$env:LOCALAPPDATA\Programs\LM Studio\resources\app\.webpack\lms.exe"

# Stop whatever /api/ps reports; fall back to the static registry list if the GET fails.
$models = @()
try {
    $raw = curl.exe -s --max-time 5 http://127.0.0.1:11434/api/ps
    if ($raw) {
        $ps = $raw | ConvertFrom-Json
        foreach ($m in $ps.models) { if ($m.name) { $models += $m.name } }
    }
} catch { $models = @() }
if ($models.Count -eq 0) {
    $models = @(
        "qwen3-8b-8k",
        "fluffy/l3-8b-stheno-v3.2:q8_0",
        "qwen3:8b",
        "hermes3:8b",
        "llama3.1:8b",
        "qwen2.5:7b",
        "qwen3.5:4b-q8_0",
        "llama3.2:3b",
        "llama3.2:1b",
        "nomic-embed-text",
        "embeddinggemma:300m-qat-q4_0"
    )
}
foreach ($m in $models) {
    Write-Host "ollama stop $m"
    & $ollama stop $m
}

Write-Host "lms unload --all"
$p = Start-Process -FilePath cmd -ArgumentList "/c echo y| `"$lms`" unload --all" -NoNewWindow -PassThru
if (-not $p.WaitForExit(60000)) { $p.Kill(); Write-Host "lms unload timed out" }

Write-Host "Ollama /api/ps:"
curl.exe -s --max-time 5 http://127.0.0.1:11434/api/ps
Write-Host ""
