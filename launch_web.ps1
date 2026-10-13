# OpenLink AI - web launcher
# Starts the web server on 127.0.0.1:8377 if it is not already running, then opens the browser.
$ProjectDir = 'E:\OpenCodeTemp\openlink AI'
$Python = 'C:\Users\mmshi\AppData\Local\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.11_qbz5n2kfra8p0\python.exe'
$Url = 'http://127.0.0.1:8377/'

function Test-Listening {
    return [bool](Get-NetTCPConnection -State Listen -LocalPort 8377 -ErrorAction SilentlyContinue)
}

if (-not (Test-Listening)) {
    Start-Process -FilePath $Python -ArgumentList 'web_server.py' -WorkingDirectory $ProjectDir -WindowStyle Minimized
}

$deadline = (Get-Date).AddSeconds(20)
while ((Get-Date) -lt $deadline -and -not (Test-Listening)) {
    Start-Sleep -Milliseconds 500
}

if (Test-Listening) {
    Start-Process $Url
    exit 0
}

Write-Host 'OpenLink AI did not start on port 8377.'
exit 1
