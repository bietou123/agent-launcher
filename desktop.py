"""Agent 启动助手 · 桌面程序入口

打包成 exe 后双击直接开原生窗口（WebView2），不起浏览器、不露网址。
在源码模式下也可以 `python desktop.py` 运行。
"""
from __future__ import annotations

import ctypes
import socket
import sys
import threading
import time
import traceback
from pathlib import Path

import webview

import app as backend


def message_box(text: str, title: str = "Agent 启动助手", error: bool = False) -> None:
    MB_ICONERROR = 0x10
    MB_ICONINFORMATION = 0x40
    ctypes.windll.user32.MessageBoxW(None, text, title, MB_ICONERROR if error else MB_ICONINFORMATION)


def wait_port(port: int, timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket() as s:
            s.settimeout(0.3)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.1)
    return False


def main() -> None:
    backend.ensure_config()
    cfg = backend.load_config()
    port = int(cfg.get("port", 8765))

    if backend.port_open(port):
        message_box("Agent 启动助手已经在运行了（窗口可能在任务栏里）。")
        return

    threading.Thread(
        target=lambda: backend.app.run(
            host="127.0.0.1", port=port, debug=False, use_reloader=False, threaded=True
        ),
        daemon=True,
    ).start()

    if not wait_port(port):
        message_box("本地服务启动超时，请查看 launcher.log。", error=True)
        return

    webview.create_window(
        "Agent 启动助手",
        f"http://127.0.0.1:{port}/",
        width=1180,
        height=620,
        min_size=(900, 480),
        background_color="#0d0f14",
        text_select=False,
    )
    webview.start()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log = backend.BASE / "launcher.log"
        with open(log, "a", encoding="utf-8") as f:
            f.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}]\n{traceback.format_exc()}")
        message_box(f"启动失败，详情见：\n{log}", error=True)
        raise
