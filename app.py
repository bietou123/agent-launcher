"""Agent 启动助手 · 后端

一个按钮 = 一个 agent 的一键启动。
服务只绑 127.0.0.1，启动命令全部来自服务端 agents.json 白名单。
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

from flask import Flask, jsonify, render_template, request


def resource_root() -> Path:
    """只读资源（templates/static/默认配置）：打包后在 exe 的解包目录里。"""
    meipass = getattr(sys, "_MEIPASS", None)
    return Path(meipass) if meipass else Path(__file__).resolve().parent


def data_root() -> Path:
    """可写数据（agents.json/state.json/launcher.log）：打包后放在 exe 旁边。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


BASE = data_root()
CONFIG_PATH = BASE / "agents.json"
STATE_PATH = BASE / "state.json"

app = Flask(
    __name__,
    template_folder=str(resource_root() / "templates"),
    static_folder=str(resource_root() / "static"),
)


def ensure_config() -> None:
    """首次运行：把内置的默认配置复制到 exe 旁边，之后用户可自行编辑。

    仓库里只有脱敏的 agents.example.json；本机实际使用的 agents.json 不进版本库。
    """
    if CONFIG_PATH.exists():
        return
    candidates = [resource_root() / "agents.json", resource_root() / "agents.example.json"]
    for default in candidates:
        if default.exists() and default.resolve() != CONFIG_PATH.resolve():
            shutil.copyfile(default, CONFIG_PATH)
            return


# ---------- 配置与状态 ----------

def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_state() -> dict:
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state: dict) -> None:
    try:
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def allowed_roots(cfg: dict) -> list[Path]:
    # allowedRoots 一旦配置就是唯一白名单：工作目录只能落在这些根之下
    explicit = cfg.get("projects", {}).get("allowedRoots")
    if explicit:
        return [Path(os.path.expandvars(item)) for item in explicit]
    roots = []
    for item in cfg.get("projects", {}).get("scan", []):
        roots.append(Path(os.path.expandvars(item)))
    for item in cfg.get("projects", {}).get("pinned", []):
        roots.append(Path(os.path.expandvars(item["path"])))
    return roots


def is_allowed_cwd(cwd: str, cfg: dict) -> bool:
    # 空路径会被 resolve 成服务进程自己的工作目录，必须显式拒绝
    if not cwd or not str(cwd).strip():
        return False
    try:
        target = Path(cwd).resolve()
    except Exception:
        return False
    if not target.is_dir():
        return False
    for root in allowed_roots(cfg):
        try:
            target.relative_to(root.resolve())
            return True
        except ValueError:
            continue
    return False


def port_open(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket() as s:
        s.settimeout(0.35)
        return s.connect_ex((host, port)) == 0


def health_probe(url: str) -> bool:
    """探测配置里的健康检查地址；只支持 http，直连避免系统代理拖慢 2 秒。"""
    import http.client
    from urllib.parse import urlparse

    try:
        u = urlparse(url)
        if u.scheme != "http" or not u.hostname:
            return False
        conn = http.client.HTTPConnection(u.hostname, u.port or 80, timeout=0.8)
        conn.request("GET", u.path or "/")
        resp = conn.getresponse()
        resp.read(64)
        conn.close()
        return 200 <= resp.status < 300
    except Exception:
        return False


def process_names() -> set[str]:
    """用 Toolhelp32 直接枚举进程名，毫秒级；不启子进程。"""
    import ctypes
    from ctypes import wintypes

    TH32CS_SNAPPROCESS = 0x00000002

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    names: set[str] = set()
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap in (0, -1):
        return names
    entry = PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
    try:
        ok = k32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            names.add(entry.szExeFile.lower())
            ok = k32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        k32.CloseHandle(snap)
    return names


# ---------- 路由 ----------

@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/agents")
def api_agents():
    cfg = load_config()
    state = load_state()
    agents = [a for a in cfg.get("agents", []) if not a.get("hidden")]

    projects = []
    seen = set()

    for item in cfg.get("projects", {}).get("pinned", []):
        p = Path(os.path.expandvars(item["path"]))
        if p.is_dir() and str(p).lower() not in seen:
            seen.add(str(p).lower())
            projects.append({"label": item["label"], "path": str(p), "kind": "pinned"})

    for root in cfg.get("projects", {}).get("scan", []):
        root_path = Path(os.path.expandvars(root))
        if not root_path.is_dir():
            continue
        for child in sorted(root_path.iterdir(), key=lambda p: p.name.lower()):
            if not child.is_dir():
                continue
            if child.name.startswith(".") or child.name in cfg.get("excludeProjects", []):
                continue
            key = str(child).lower()
            if key in seen:
                continue
            seen.add(key)
            projects.append({"label": child.name, "path": str(child), "kind": "project"})

    default_cwd = next((p["path"] for p in projects if p["kind"] == "project"), None)
    if not default_cwd:
        roots = allowed_roots(cfg)
        default_cwd = str(roots[0]) if roots else str(Path.home())

    last_cwd = state.get("lastCwd")
    if not last_cwd or not is_allowed_cwd(last_cwd, cfg):
        last_cwd = default_cwd

    return jsonify({
        "agents": agents,
        "projects": projects,
        "lastCwd": last_cwd,
        "lastLaunched": state.get("lastLaunched"),
    })


@app.get("/api/status")
def api_status():
    cfg = load_config()
    health_cfg = cfg.get("health") or {}
    health_url = health_cfg.get("url")
    health = {
        "label": health_cfg.get("label") or "健康检查",
        "configured": bool(health_url),
        "ok": health_probe(health_url) if health_url else None,
    }
    procs = process_names()
    running = {}
    for agent in cfg.get("agents", []):
        # CLI 类每次都是独立终端会话，只对 GUI 类做进程检测
        img = agent.get("process")
        if agent.get("type") == "gui" and img:
            running[agent["id"]] = img.lower() in procs
    return jsonify({"health": health, "running": running})


def launch_argv(agent: dict, cwd: str) -> tuple[list[str], str]:
    """把 agent 配置翻译成 (argv, 工作目录)，不执行。

    CLI 走 Windows Terminal，GUI 直接起 exe；两条路径都是纯函数，便于验证。
    """
    if agent.get("type") == "cli":
        return ["wt.exe", "-d", cwd, "cmd", "/k", agent["command"]], cwd
    if agent.get("type") == "gui":
        exe = Path(os.path.expandvars(agent["exe"]))
        workdir = str(exe.parent) if agent.get("cwd") == "exe" else cwd
        return [str(exe)], workdir
    raise ValueError("未支持的 agent 类型")


@app.post("/api/launch")
def api_launch():
    cfg = load_config()
    body = request.get_json(silent=True) or {}
    agent_id = body.get("agentId")
    cwd = body.get("cwd") or ""

    agent = next((a for a in cfg.get("agents", []) if a.get("id") == agent_id), None)
    if not agent:
        return jsonify({"ok": False, "error": "未知的 agent"}), 400

    if not is_allowed_cwd(cwd, cfg):
        return jsonify({"ok": False, "error": f"工作目录不被允许：{cwd}"}), 400

    try:
        argv, workdir = launch_argv(agent, cwd)
        if agent.get("type") == "gui" and not Path(argv[0]).exists():
            return jsonify({"ok": False, "error": f"找不到程序：{argv[0]}"}), 400
        subprocess.Popen(argv, cwd=workdir, close_fds=True)
    except Exception as exc:
        return jsonify({"ok": False, "error": f"启动失败：{exc}"}), 500

    state = load_state()
    state["lastCwd"] = cwd
    state["lastLaunched"] = {"id": agent_id, "name": agent["name"], "cwd": cwd, "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    save_state(state)

    return jsonify({"ok": True, "name": agent["name"]})


# ---------- 开发模式 ----------

def main() -> None:
    """源码模式：只跑本地服务（窗口由 desktop.py 负责）。"""
    ensure_config()
    cfg = load_config()
    port = int(cfg.get("port", 8765))
    if port_open(port):
        print(f"端口 {port} 已被占用，服务可能已在运行：http://127.0.0.1:{port}/")
        return
    print(f"http://127.0.0.1:{port}/")
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        with open(BASE / "launcher.log", "a", encoding="utf-8") as f:
            f.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}]\n{traceback.format_exc()}")
        raise
