"""离线验证：走真实 Flask 路由，但拦住 subprocess.Popen 和 state.json 写入。

用临时目录造一份自包含的测试配置，不依赖本机装了哪些 agent，
也不启动任何进程、不弹任何窗口。

覆盖：CLI / GUI 两种启动参数、工作目录白名单、状态记录、单实例端口探测、示例配置复制。
"""
import json
import os
import sys
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

import app as launcher  # noqa: E402

captured = []
saved_state = []


class FakePopen:
    def __init__(self, argv, cwd=None, **kwargs):
        captured.append({"argv": argv, "cwd": cwd, "kwargs": kwargs})


launcher.subprocess.Popen = FakePopen
launcher.save_state = saved_state.append  # 不写盘，只记录

tmp = Path(tempfile.mkdtemp(prefix="agent-launcher-verify-"))
projects = tmp / "Projects"
demo = projects / "demo"
demo.mkdir(parents=True)
fake_cmd = tmp / "bin" / "fake-agent.cmd"
fake_cmd.parent.mkdir()
fake_cmd.write_text("@echo off\n", encoding="utf-8")
fake_exe = tmp / "bin" / "fake-gui.exe"
fake_exe.write_bytes(b"MZ")

cfg = {
    "port": 8765,
    "projects": {"scan": [str(projects)], "pinned": [], "allowedRoots": [str(projects)]},
    "excludeProjects": ["AgentLauncher"],
    "agents": [
        {
            "id": "cli-agent",
            "name": "测试 CLI",
            "group": "cli",
            "type": "cli",
            "command": str(fake_cmd),
            "process": "node.exe",
        },
        {
            "id": "gui-agent",
            "name": "测试 GUI",
            "group": "gui",
            "type": "gui",
            "exe": str(fake_exe),
            "cwd": "exe",
            "process": "fake-gui.exe",
        },
    ],
}

cfg_path = tmp / "agents.json"
cfg_path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
launcher.CONFIG_PATH = cfg_path
launcher.STATE_PATH = tmp / "state.json"

client = launcher.app.test_client()

# 1. 两种启动参数与工作目录
print(f"[1/5] 逐个下发启动请求（工作目录 {demo}）：")
for agent in cfg["agents"]:
    resp = client.post("/api/launch", json={"agentId": agent["id"], "cwd": str(demo)})
    data = resp.get_json()
    assert resp.status_code == 200 and data["ok"], f"{agent['id']} 失败: {data}"
    call = captured[-1]
    argv, workdir = call["argv"], call["cwd"]
    if agent["type"] == "cli":
        assert argv == ["wt.exe", "-d", str(demo), "cmd", "/k", agent["command"]], argv
        assert workdir == str(demo), workdir
        assert Path(argv[-1]).exists(), argv[-1]
    else:
        assert argv == [agent["exe"]], argv
        assert Path(argv[0]).exists(), argv[0]
        assert workdir == str(fake_exe.parent), workdir
    print(f"      {agent['name']:<10} {' '.join(argv)}")

# 2. 工作目录白名单
bad = [
    {"agentId": "nope", "cwd": str(demo)},
    {"agentId": "cli-agent", "cwd": str(tmp)},
    {"agentId": "cli-agent", "cwd": str(tmp / "..")},
    {"agentId": "cli-agent", "cwd": str(tmp / "not-exist")},
    {"agentId": "cli-agent"},
]
for payload in bad:
    r = client.post("/api/launch", json=payload)
    assert r.status_code == 400, f"{payload} 应被拒绝，实际 {r.status_code}"
print(f"[2/5] {len(bad)} 种非法启动请求全部 400 拦截（未知 id / 越界 / .. 绕过 / 不存在 / 空）")

# 3. 项目列表与启动记录
r = client.get("/api/agents").get_json()
assert len(r["agents"]) == 2, r
assert [p["label"] for p in r["projects"]] == ["demo"], r["projects"]
assert r["lastCwd"] == str(demo), r
assert saved_state and saved_state[-1]["lastLaunched"]["id"] == "gui-agent", saved_state[-3:]
print(f"[3/5] /api/agents 返回 {len(r['agents'])} 个 agent、{len(r['projects'])} 个工作目录；启动记录已写入")

# 4. 健康检查与单实例端口探测
st = client.get("/api/status").get_json()
assert st["health"] == {"label": "健康检查", "configured": False, "ok": None}, st
assert isinstance(launcher.port_open(8765), bool)
print("[4/5] /api/status 健康检查未配置时返回 configured=false；端口探测正常")

# 5. 示例配置：全新目录首次运行能复制出来（把资源根指向只含 example 的临时目录，
#    避免本机 agents.json 干扰）
example = BASE / "agents.example.json"
assert example.exists(), "缺少 agents.example.json"
res = tmp / "res"
res.mkdir()
(res / "agents.example.json").write_bytes(example.read_bytes())
launcher.resource_root = lambda: res
launcher.CONFIG_PATH = tmp / "fresh" / "agents.json"
launcher.CONFIG_PATH.parent.mkdir()
launcher.ensure_config()
assert launcher.CONFIG_PATH.exists(), "首次运行未复制示例配置"
fresh_cfg = json.loads(launcher.CONFIG_PATH.read_text(encoding="utf-8"))
assert fresh_cfg["agents"], "示例配置没有 agent"
print("[5/5] 首次运行能从 agents.example.json 生成 agents.json")

print("\n全部通过，未启动任何进程。")
