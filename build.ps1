# Rebuild the exe: output is "<product name>.exe" in this folder.
# Requirements: Python 3.10+, pip install pyinstaller pywebview flask
# Keep this file ASCII-only: Windows PowerShell 5.1 reads BOM-less files as
# ANSI/GBK, so non-ASCII literals would be garbled (especially the file name).
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$py = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $py) { throw "python not found; install Python 3 and add it to PATH" }

# Always bundle the sanitized agents.example.json. Never bundle the local
# agents.json: it contains personal paths. app.ensure_config() copies the
# example to agents.json next to the exe on first run.
if (-not (Test-Path "agents.example.json")) { throw "agents.example.json missing" }
$cfg = "agents.example.json"

# Build the Chinese output name from code points to keep this script ASCII.
# 0x542F 0x52A8 0x52A9 0x624B = qi dong zhu shou
$outName = "Agent " + [char]0x542F + [char]0x52A8 + [char]0x52A9 + [char]0x624B + ".exe"

& $py -m PyInstaller --noconfirm --clean --onefile --windowed `
    --name AgentLauncher `
    --icon app.ico `
    --add-data "templates;templates" `
    --add-data "static;static" `
    --add-data "$cfg;." `
    --hidden-import=webview.platforms.winforms `
    --hidden-import=clr `
    desktop.py

Copy-Item "dist\AgentLauncher.exe" $outName -Force
Remove-Item build, dist, AgentLauncher.spec -Recurse -Force -ErrorAction SilentlyContinue
Write-Host "Done: $PSScriptRoot\$outName"
