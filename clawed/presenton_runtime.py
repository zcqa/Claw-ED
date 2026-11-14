"""Run the private PPT engine with the workbench's existing model settings."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time

import httpx

from clawed.config import get_api_key
from clawed.models import AppConfig
from clawed.workbench import workspace

CONTAINER = "clawed-presenton"
IMAGE = "ghcr.io/presenton/presenton@sha256:18b7331753e133de2272db1b2ab0d92de75a8fc6c14e1dea81bb8a9edb8a4e95"
PORT = 5002


def install_bridge() -> None:
    source = Path(__file__).with_name("presenton_bridge.py")
    limits = source.with_name("ppt_limits.py")
    subprocess.run(["docker", "cp", str(limits), CONTAINER + ":/app/servers/fastapi/clawed_ppt_limits.py"], check=True)
    subprocess.run(["docker", "cp", str(source), CONTAINER + ":/app/servers/fastapi/clawed_bridge.py"], check=True)
    patch = ("from pathlib import Path; p=Path('/app/servers/fastapi/api/main.py'); "
             "s=p.read_text(); hook='\\nfrom clawed_bridge import install as install_clawed_bridge\\ninstall_clawed_bridge(app)\\n'; "
             "p.write_text(s if 'install_clawed_bridge(app)' in s else s+hook)")
    subprocess.run(["docker", "exec", CONTAINER, "python", "-c", patch], check=True)
    subprocess.run(["docker", "restart", CONTAINER], check=True)


def wait_ready() -> None:
    with httpx.Client(base_url=f"http://127.0.0.1:{PORT}", timeout=3, trust_env=False) as client:
        for _ in range(90):
            try:
                response = client.get("/api/v1/auth/status")
                if response.status_code == 200:
                    bridge = client.get("/api/v1/clawed/status")
                    expected = hashlib.sha256(Path(__file__).with_name("presenton_bridge.py").read_bytes()).hexdigest()
                    limits_hash = hashlib.sha256(Path(__file__).with_name("ppt_limits.py").read_bytes()).hexdigest()
                    if (bridge.status_code == 200 and bridge.json().get("bridge_sha256") == expected
                            and bridge.json().get("limits_sha256") == limits_hash):
                        print(f"课件引擎已就绪（仅本机 {PORT} 端口）。", flush=True)
                        return
                    if bridge.status_code == 200 and bridge.json().get("active"):
                        raise ValueError("课件正在生成，请完成或取消当前任务后再更新引擎。")
                    install_bridge()
            except httpx.RequestError:
                pass
            time.sleep(1)
    raise ValueError("课件引擎启动未完成，请查看 Docker 中 clawed-presenton 的运行状态。")


def settings(config: AppConfig | None = None) -> dict:
    cfg = config or AppConfig.load()
    provider = cfg.provider.value
    values = {
        "LLM": provider,
        "DISABLE_IMAGE_GENERATION": True,
        "WEB_GROUNDING": False,
        "DISABLE_THINKING": not cfg.deepseek_thinking,
    }
    names = {"deepseek": "DEEPSEEK", "openai": "OPENAI", "anthropic": "ANTHROPIC",
             "google": "GOOGLE", "ollama": "OLLAMA", "openrouter": "OPENROUTER"}
    prefix = names[provider]
    values[prefix + "_MODEL"] = getattr(cfg, provider + "_model")
    if provider != "ollama":
        key = get_api_key(provider)
        if not key:
            raise ValueError("请先在工作台模型设置中配置 API Key。")
        values[prefix + "_API_KEY"] = key
    if provider == "deepseek":
        values["DEEPSEEK_BASE_URL"] = cfg.deepseek_base_url
    return values


def run(action: str) -> None:
    try:
        daemon = subprocess.run(["docker", "info", "--format", "{{.OSType}}"], capture_output=True)
    except FileNotFoundError as exc:
        raise ValueError("未找到 Docker，请先安装并启动 Docker Desktop。") from exc
    if daemon.returncode:
        raise ValueError("Docker 尚未就绪，请先打开 Docker Desktop，等待引擎启动后重试。")
    if action == "status":
        subprocess.run(["docker", "ps", "-a", "--filter", "name=^/" + CONTAINER + "$",
                        "--format", "{{.Names}}: {{.Status}} ({{.Ports}})"], check=True)
        return
    if action == "stop":
        subprocess.run(["docker", "stop", CONTAINER], check=True)
        return
    if action == "bridge":
        install_bridge()
        return
    root = workspace() / "presenton"
    root.mkdir(parents=True, exist_ok=True)
    config = root / "userConfig.json"
    if not config.is_file():
        config.write_text(json.dumps(settings(), ensure_ascii=False), encoding="utf-8")
    # Credentials are in a local runtime file, never in CLI arguments or logs.
    found = subprocess.run(["docker", "container", "inspect", CONTAINER], capture_output=True)
    if found.returncode == 0:
        subprocess.run(["docker", "start", CONTAINER], check=True)
        wait_ready()
        return
    args = ["docker", "run", "-d", "--name", CONTAINER, "--restart", "unless-stopped",
            "--memory", "3g", "--cpus", "2", "--shm-size", "256m",
            "-p", f"127.0.0.1:{PORT}:80", "--mount", f"type=bind,source={root},target=/app_data",
            "-e", "USER_CONFIG_PATH=/app_data/userConfig.json", "-e", "DISABLE_AUTH=true",
            "-e", "PRESENTATION_GENERATION_MODE=standard", "-e", "PRESENTON_COMMUNITY_ENABLED=false",
            "-e", "MAX_OUTLINE_WORDS=2000", "-e", "DISABLE_IMAGE_GENERATION=true",
            "-e", "CAN_CHANGE_KEYS=false", IMAGE]
    subprocess.run(args, check=True)
    subprocess.run(["docker", "start", CONTAINER], check=True)
    wait_ready()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="启动、停止或查看本机 PPT 引擎。")
    parser.add_argument("action", choices=["start", "stop", "status", "bridge"], default="start", nargs="?")
    try:
        run(parser.parse_args().action)
    except (ValueError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"课件服务操作未完成：{exc if isinstance(exc, ValueError) else '请查看 Docker 中 clawed-presenton 的运行状态。'}\n")
