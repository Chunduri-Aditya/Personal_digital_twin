# Append "<time> <GET /api/ps body>" to data/ps_poll.log every 0.5 s for 120 s (Stage 5 evidence).
$log = "C:/Users/Adity/Personal_digital_twin/data/ps_poll.log"
$end = (Get-Date).AddSeconds(120)
while ((Get-Date) -lt $end) {
    $body = curl.exe -s --max-time 2 http://127.0.0.1:11434/api/ps
    "$(Get-Date -Format HH:mm:ss.fff) $body" | Add-Content -Encoding utf8 $log
    Start-Sleep -Milliseconds 500
}
