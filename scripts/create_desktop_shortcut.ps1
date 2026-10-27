# Creates a "MotorSift" shortcut that starts the app (Windows).
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\create_desktop_shortcut.ps1
#         (optional) -Destination "C:\some\folder"   (defaults to your Desktop)
param([string]$Destination = [Environment]::GetFolderPath("Desktop"))

$root = Split-Path -Parent $PSScriptRoot
$target = Join-Path $root "run.bat"
if (-not (Test-Path $target)) { throw "run.bat not found at $target" }

$shell = New-Object -ComObject WScript.Shell
$lnkPath = Join-Path $Destination "MotorSift.lnk"
$lnk = $shell.CreateShortcut($lnkPath)
$lnk.TargetPath = $target
$lnk.WorkingDirectory = $root
$lnk.WindowStyle = 7   # start minimized; the app opens in your browser
$lnk.Description = "MotorSift - local vehicle-shopping workspace"
$lnk.IconLocation = "$env:SystemRoot\System32\imageres.dll,186"
$lnk.Save()
Write-Host "Created $lnkPath"
