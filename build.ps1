# 重新打包 exe：产物是项目根目录下的「Agent 启动助手.exe」
# 依赖：Python 3.10+、pip install pyinstaller pywebview flask
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$py = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $py) { throw "找不到 python，请先安装 Python 3 并加入 PATH" }

# 始终内置脱敏的 agents.example.json，避免把本机 agents.json 里的个人路径打进发布包。
# 首次运行由 app.ensure_config() 复制成 exe 旁边的 agents.json，之后用户自行编辑。
if (-not (Test-Path "agents.example.json")) { throw "缺少 agents.example.json" }
$cfg = "agents.example.json"

& $py -m PyInstaller --noconfirm --clean --onefile --windowed `
    --name AgentLauncher `
    --icon app.ico `
    --add-data "templates;templates" `
    --add-data "static;static" `
    --add-data "$cfg;." `
    --hidden-import=webview.platforms.winforms `
    --hidden-import=clr `
    desktop.py

Copy-Item "dist\AgentLauncher.exe" "Agent 启动助手.exe" -Force
Remove-Item build, dist, AgentLauncher.spec -Recurse -Force -ErrorAction SilentlyContinue
Write-Host "打包完成：$PSScriptRoot\Agent 启动助手.exe"
