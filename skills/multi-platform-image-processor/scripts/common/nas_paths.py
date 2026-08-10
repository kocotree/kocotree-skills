from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path


logger = logging.getLogger(__name__)
DRIVE_PATTERN = re.compile(r"^(?P<drive>[A-Za-z]:)(?P<tail>[\\/].*)?$")
UNC_PATTERN = re.compile(r"^\\\\[^\\]+\\[^\\]+")


def discover_drive_mappings() -> dict[str, str]:
    """读取 Windows 当前用户的网络盘映射。

    返回值：
        盘符到 UNC 根目录的映射，盘符统一为大写。
    """
    if not hasattr(subprocess, "run"):
        return {}
    try:
        result = subprocess.run(
            ["net", "use"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("网络盘映射读取失败：%s", exc)
        return {}
    mappings: dict[str, str] = {}
    for line in result.stdout.splitlines():
        drive = re.search(r"(?<![A-Za-z])([A-Za-z]:)(?![A-Za-z])", line)
        unc = re.search(r"(\\\\[^\s\\]+\\[^\s]+)", line)
        if drive and unc:
            mappings[drive.group(1).upper()] = unc.group(1).rstrip("\\/")
    return mappings


def to_unc_path(value: str | Path, mappings: dict[str, str] | None = None) -> Path:
    """将映射盘路径转换为 UNC 路径。

    参数：
        value：UNC、本地路径或映射盘路径。
        mappings：可注入的盘符映射；未提供时读取系统映射。
    返回值：
        UNC 路径或原始本地路径。
    """
    raw = str(value).strip()
    if UNC_PATTERN.match(raw):
        return Path(raw.replace("/", "\\"))
    match = DRIVE_PATTERN.match(raw)
    if not match:
        return Path(raw)
    drive = match.group("drive").upper()
    mapping = (mappings if mappings is not None else discover_drive_mappings()).get(drive)
    if not mapping:
        return Path(raw)
    tail = (match.group("tail") or "").lstrip("\\/").replace("/", "\\")
    converted = mapping if not tail else f"{mapping}\\{tail}"
    logger.info("映射盘路径已转换 drive=%s unc=%r", drive, converted)
    return Path(converted)


def require_accessible_directory(path: Path, label: str) -> Path:
    """确认外部目录存在且可枚举。

    参数：
        path：需要检查的目录。
        label：报告中使用的目录名称。
    返回值：
        验证通过的目录路径。
    """
    if not path.is_dir():
        raise RuntimeError(f"{label}不可访问：{path}")
    try:
        next(path.iterdir(), None)
    except OSError as exc:
        raise RuntimeError(f"{label}无法读取：{path}，{exc}") from exc
    logger.info("外部目录访问检查通过 label=%s path=%r", label, str(path))
    return path
