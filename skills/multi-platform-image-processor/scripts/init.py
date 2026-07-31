from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from pathlib import Path

from auth.auth_client import ensure_token
from common.environment import save_environment_state
from common.image_resize_compress import find_pngquant
from common.text_removal import initialize_text2image


logger = logging.getLogger(__name__)

MACOS_PNGQUANT_DEPENDENCIES = {
    "liblcms2": "little-cms2",
    "little-cms2": "little-cms2",
    "libpng": "libpng",
}


def validate_current_venv() -> None:
    """确认初始化脚本运行在当前 skill 的虚拟环境中。"""
    expected = Path(__file__).resolve().parent / ".venv"
    if Path(sys.prefix).resolve() != expected.resolve():
        raise RuntimeError("请在 scripts 目录使用 uv run init.py 执行初始化")


def run_pngquant_version(executable: str) -> subprocess.CompletedProcess[str]:
    """执行 pngquant 版本检查并返回子进程结果。"""
    return subprocess.run(
        [executable, "--version"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
    )


def find_missing_macos_dependencies(detail: str) -> list[str]:
    """从 pngquant 错误信息中识别缺少的 macOS 运行库。"""
    if sys.platform != "darwin":
        return []
    lowered = detail.lower()
    return sorted(
        {
            formula
            for marker, formula in MACOS_PNGQUANT_DEPENDENCIES.items()
            if marker in lowered
        },
    )


def install_homebrew_dependencies(formulas: list[str]) -> None:
    """使用 Homebrew 安装 macOS 运行库。

    功能说明：调用当前系统中的 Homebrew 安装 pngquant 明确缺少的运行库。
    参数：
        formulas：需要安装的 Homebrew formula 名称列表。
    返回值：
        无。
    """
    brew = shutil.which("brew")
    if not brew:
        raise RuntimeError(
            "pngquant 缺少 macOS 运行库，且未找到 Homebrew；"
            "请先安装 Homebrew，再重新执行 uv run init.py",
        )
    logger.warning("pngquant缺少macOS运行库，开始安装：%s", ", ".join(formulas))
    result = subprocess.run(
        [brew, "install", *formulas],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(
            f"Homebrew安装pngquant运行库失败："
            f"{detail[:500] or f'退出码 {result.returncode}'}",
        )
    logger.info("pngquant的macOS运行库安装完成：%s", ", ".join(formulas))


def validate_pngquant() -> Path:
    """查找、补齐运行库并实际执行 pngquant。

    功能说明：定位 pngquant，通过版本命令验证执行环境，并在 macOS
    明确缺少 Homebrew 运行库时自动安装后重新验证。
    返回值：
        验证通过的 pngquant 可执行文件路径。
    """
    executable = find_pngquant()
    if not executable:
        raise RuntimeError("未找到 pngquant 可执行文件")
    installed: set[str] = set()
    while True:
        result = run_pngquant_version(executable)
        if result.returncode == 0:
            return Path(executable)
        detail = (result.stderr or result.stdout).strip()
        missing = [
            formula
            for formula in find_missing_macos_dependencies(detail)
            if formula not in installed
        ]
        if not missing:
            raise RuntimeError(
                detail[:500] or f"pngquant 退出码 {result.returncode}",
            )
        install_homebrew_dependencies(missing)
        installed.update(missing)


def initialize_environment() -> Path:
    """初始化图片处理所需的本地环境和飞书认证。

    功能说明：依次验证当前 `.venv`、pngquant 和 text2image，保存环境
    状态后执行飞书认证。
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

    state_path = save_environment_state(pngquant, text2image)
    logger.info("环境状态写入完成：%s", state_path)

    ensure_token()
    logger.info("飞书认证检查完成")
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
