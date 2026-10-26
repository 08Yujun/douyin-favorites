# Double-click launcher for the favorites UI (ASCII only; keep it ASCII!)
$port = 8642
if (-not (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)) {
    Start-Process python -ArgumentList 'main.py','web' -WindowStyle Hidden
    foreach ($i in 1..20) {
        Start-Sleep -Seconds 1
        if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) { break }
    }
}
Start-Process 'http://127.0.0.1:8642/'
