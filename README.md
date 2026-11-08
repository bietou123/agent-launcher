# Agent 启动助手

桌面上的按钮墙：**一个按钮 = 一个 agent 一键启动**。点下去就开好终端、进好工作目录，不用再开命令行、cd、配环境。

Windows 11 上的原生窗口（pywebview + WebView2），单文件 exe，双击即用，不需要装 Python。

## 功能

- **工作目录条**：扫描配置里的项目根目录，列出全部一级子目录；也可以钉几个固定目录。选中的目录记在 `state.json`，下次打开还是它。
- **一键启动**：CLI 类在 Windows Terminal 里用 `cmd /k` 打开并可交互；GUI 类直接启动 exe，工作目录可设为 exe 所在目录。
- **单实例**：已经在运行时再双击，会提示「已经在运行」，不会起第二个实例。
- **健康灯**：默认不启用。配置 `health.url` 后，右上角圆点每 10 秒探测一次该地址。

## 安全模型

这是本项目的核心约束，值得单独说明：

1. **启动命令只存在于服务端的 `agents.json`**。页面只传 `agentId` + `cwd`，程序不会执行任何来自页面的命令字符串——即使前端被注入，也拉不起别的进程。
2. **工作目录白名单**：`projects.allowedRoots` 是唯一白名单，`cwd` 必须落在这些根目录之内。`..` 绕出、不存在的目录、空路径一律返回 400。
3. **只监听 `127.0.0.1`**，不对局域网开放。

## 快速开始

### 直接运行源码

```powershell
pip install flask pywebview
python desktop.py
```

首次运行会把 `agents.example.json` 复制成同目录的 `agents.json`，按自己的环境改这个文件后重启即可。

### 打包成 exe

```powershell
.\build.ps1
```

需要 Python 3.10+ 与 `pyinstaller`、`pywebview`、`flask`。产物是根目录下的 `Agent 启动助手.exe`（约 18 MB）。

打包时**固定内置脱敏的 `agents.example.json`**，不会把你本机的 `agents.json` 打进发布包。

## 配置 `agents.json`

```json
{
  "port": 8765,
  "projects": {
    "scan": ["%USERPROFILE%\\Projects"],
    "pinned": [{ "label": "临时目录", "path": "%TEMP%" }],
    "allowedRoots": ["%USERPROFILE%\\Projects", "%TEMP%"]
  },
  "excludeProjects": ["AgentLauncher"],
  "agents": [
    {
      "id": "my-agent",
      "name": "我的 Agent",
      "subtitle": "一行说明",
      "group": "cli",
      "type": "cli",
      "command": "%APPDATA%\\npm\\claude.cmd",
      "icon": "M",
      "color": "#4d6bfe",
      "process": "node.exe"
    },
    {
      "id": "my-app",
      "name": "我的应用",
      "group": "gui",
      "type": "gui",
      "exe": "C:\\Program Files\\App\\app.exe",
      "cwd": "exe",
      "icon": "A",
      "color": "#3fbf7f",
      "process": "app.exe"
    }
  ]
}
```

| 字段 | 说明 |
|---|---|
| `projects.scan` | 扫描项目列表的根目录，列出其一级子目录 |
| `projects.pinned` | 固定显示的目录项 |
| `projects.allowedRoots` | 工作目录白名单；配置后 `scan` / `pinned` 不再参与放行判断 |
| `excludeProjects` | 扫描时跳过的目录名 |
| `type: "cli"` | 在 Windows Terminal 里 `cmd /k <command>` 启动 |
| `type: "gui"` | 直接启动 `exe`；`"cwd": "exe"` 表示工作目录设为 exe 所在目录 |
| `hidden` | 置为 `true` 临时隐藏卡片 |
| `health` | 可选。`{"label": "本地网关", "url": "http://127.0.0.1:8787/health"}`，右上角圆点每 10 秒探测一次该地址；不配置则显示灰色「未配置健康检查」 |

路径里的 `%APPDATA%`、`%USERPROFILE%` 等环境变量会被展开。

## 目录结构

```
AgentLauncher/
├── desktop.py             # exe 入口：后台起 Flask + 开原生 WebView2 窗口
├── app.py                 # Flask 服务 + 启动调度
├── agents.example.json    # 脱敏示例配置（首次运行复制成 agents.json）
├── templates/index.html   # 按钮墙
├── static/style.css       # 深色面板样式
├── app.ico                # 图标
├── build.ps1              # 重新打包 exe
└── verify.py              # 离线验证：走真实路由但拦住 Popen，不弹窗
```

运行时会在程序旁边生成 `agents.json`、`state.json`、`launcher.log`，三者都不进版本库。

## 验证

```powershell
python verify.py
```

走真实的 `/api/launch` 路由，但把 `subprocess.Popen` 换成假的，**不会真的弹出任何窗口**。用临时目录造自包含的测试配置，不依赖本机装了哪些 agent。

检查项：CLI / GUI 两种启动参数、5 种非法请求是否 400、项目列表与状态记录、端口探测、示例配置复制。

## 已知限制

- **CLI 类不做进程状态检测**：Claude Code、Codex 等都是 `node.exe`，按进程名判断会全部误报「运行中」，所以只有 GUI 卡片显示运行小圆点。
- **首次启动约 2–4 秒**：单文件 exe 需要先解包到临时目录，之后窗口打开就正常。
- **依赖 Windows**：Windows Terminal、WebView2、Toolhelp32 进程枚举都是 Windows 专有；没有做跨平台。

## 许可

[MIT](LICENSE)
