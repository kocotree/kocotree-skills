from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

from auth.auth_client import initialize_token
from common.environment import save_environment_state
from common.image_resize_compress import find_pngquant
from common.text_removal import initialize_text2image


logger = logging.getLogger(__name__)


def validate_current_venv() -> None:
    """确认初始化脚本运行在当前 skill 的虚拟环境中。"""
    expected = Path(__file__).resolve().parent / ".venv"
    if Path(sys.prefix).resolve() != expected.resolve():
        raise RuntimeError("请在 scripts 目录使用 uv run init.py 执行初始化")


def validate_pngquant() -> Path:
    """查找并实际执行 pngquant。

    功能说明：定位 pngquant 并通过版本命令验证其动态库和执行环境。
    返回值：
        验证通过的 pngquant 可执行文件路径。
    """
    executable = find_pngquant()
    if not executable:
        raise RuntimeError("未找到 pngquant 可执行文件")
    result = subprocess.run(
        [executable, "--version"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(detail[:500] or f"pngquant 退出码 {result.returncode}")
    return Path(executable)


def initialize_environment() -> Path:
    """初始化图片处理所需的本地环境和飞书认证。

    功能说明：依次验证当前 `.venv`、pngquant、text2image 和飞书认证，
    全部成功后保存初始化状态。
    返回值：
        初始化成功后写入的环境状态文件路径。
    """
    logger.info("开始初始化多平台图片处理环境")
    validate_current_venv()
    logger.info("Python虚拟环境验证完成：%s", sys.prefix)

    pngquant = validate_pngquant()
    logger.info("pngquant验证完成：%s", pngquant)

    text2image, message = initialize_text2image()
    if text2image is None:
        raise RuntimeError(message)
    logger.info("text2image初始化完成：%s", text2image)

    initialize_token()
    logger.info("飞书认证初始化完成")

    state_path = save_environment_state(pngquant, text2image)
    logger.info("环境初始化完成：%s", state_path)
    return state_path


def main() -> int:
    """执行环境初始化命令。

    功能说明：配置日志、执行完整初始化并输出最终状态文件路径。
    返回值：
        初始化成功返回 0，失败返回 1。
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    try:
        state_path = initialize_environment()
    except Exception as exc:
        logger.error("环境初始化失败：%s", exc)
        return 1
    print(f"初始化完成：{state_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
