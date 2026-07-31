from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any


STATE_VERSION = 1


def environment_state_path() -> Path:
    """返回当前 skill 虚拟环境中的初始化状态文件路径。"""
    return Path(__file__).resolve().parents[1] / ".venv" / "environment.json"


def save_environment_state(pngquant: Path, text2image_skill: Path) -> Path:
    """保存初始化完成后的运行环境路径。

    功能说明：将已验证的工具路径写入当前 `.venv`，供图片处理入口读取。
    参数：
        pngquant：已验证可执行的 pngquant 路径。
        text2image_skill：已初始化的 text2image skill 目录。
    返回值：
        初始化状态文件路径。
    """
    path = environment_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "版本": STATE_VERSION,
        "初始化时间": datetime.now().isoformat(timespec="seconds"),
        "Python": sys.executable,
        "pngquant": str(pngquant.resolve()),
        "text2image": str(text2image_skill.resolve()),
    }
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)
    load_environment_state.cache_clear()
    return path


@lru_cache(maxsize=1)
def load_environment_state() -> dict[str, Any]:
    """读取并校验初始化状态。

    功能说明：读取当前 `.venv` 中的状态文件并校验结构版本和必要字段。
    返回值：
        包含工具路径和初始化信息的状态数据。
    """
    path = environment_state_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("环境未初始化，请在 scripts 目录执行：uv run init.py") from exc
    if data.get("版本") != STATE_VERSION:
        raise RuntimeError("初始化状态版本不匹配，请在 scripts 目录重新执行：uv run init.py")
    if not data.get("pngquant") or not data.get("text2image"):
        raise RuntimeError("初始化状态不完整，请在 scripts 目录重新执行：uv run init.py")
    return data


def configure_runtime_environment() -> dict[str, Any]:
    """加载初始化结果并配置当前处理进程。

    功能说明：将状态文件中的工具路径注入当前进程，不执行安装或工具探测。
    返回值：
        当前 skill 的初始化状态数据。
    """
    data = load_environment_state()
    os.environ["PNGQUANT_BIN"] = str(data["pngquant"])
    os.environ["TEXT2IMAGE_SKILL_DIR"] = str(data["text2image"])
    return data
