# Stage-0 health check: both local model servers answer with JSON and the GPU is idle.
$ErrorActionPreference = "Continue"
$ok = $true

$lmsBody = curl.exe -s --max-time 5 http://127.0.0.1:1234/api/v0/models
Write-Host "LM Studio /api/v0/models:"
Write-Host $lmsBody
try { $null = $lmsBody | ConvertFrom-Json } catch { Write-Host "  -> not JSON"; $ok = $false }
if (-not $lmsBody) { Write-Host "  -> empty"; $ok = $false }

$ollamaBody = curl.exe -s --max-time 5 http://127.0.0.1:11434/api/tags
Write-Host "Ollama /api/tags:"
Write-Host $ollamaBody
try { $null = $ollamaBody | ConvertFrom-Json } catch { Write-Host "  -> not JSON"; $ok = $false }
if (-not $ollamaBody) { Write-Host "  -> empty"; $ok = $false }

$gpu = nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu --format=csv,noheader
Write-Host "nvidia-smi: $gpu"
$used = -1
if ($gpu) {
    $first = ($gpu -split ",")[0].Trim()
    $num = ($first -replace "[^0-9]", "")
    if ($num) { $used = [int]$num }
}
if ($used -lt 0) { Write-Host "  -> could not read GPU memory"; $ok = $false }
elseif ($used -gt 200) { Write-Host "  -> GPU memory used $used MiB > 200 MiB (something is loaded; run scripts\free_gpu.ps1)"; $ok = $false }

if ($ok) { Write-Host "PASS"; exit 0 } else { Write-Host "FAIL"; exit 1 }
