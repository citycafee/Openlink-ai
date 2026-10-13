# OpenLink AI - desktop launcher
# Starts the OpenLink AI terminal in a new console window (hidden launcher).
$ProjectDir = 'E:\OpenCodeTemp\openlink AI'
$Python = 'C:\Users\mmshi\AppData\Local\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.11_qbz5n2kfra8p0\python.exe'
$Title = 'Openlink AI'

$existing = Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -like '*run.py*' -and $_.CommandLine -like '*openlink*'
}

if ($existing) {
    $ws = New-Object -ComObject WScript.Shell
    [void]$ws.AppActivate($Title)
    exit 0
}

Start-Process -FilePath $Python -ArgumentList 'run.py','chat' -WorkingDirectory $ProjectDir
