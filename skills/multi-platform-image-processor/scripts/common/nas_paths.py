from __future__ import annotations

import logging
import os
import re
import shutil
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


def list_files_fast(
    root: Path,
    suffixes: set[str],
    name_contains: str = "",
) -> list[Path]:
    """快速枚举本地或 UNC 目录中的目标文件。

    参数：
        root：递归扫描根目录。
        suffixes：允许的扩展名集合。
        name_contains：可选的文件名包含文本。
    返回值：
        自然路径顺序排列的文件列表。
    """
    normalized_suffixes = {suffix.casefold() for suffix in suffixes}
    if os.name == "nt" and str(root).startswith("\\\\"):
        powershell = shutil.which("powershell.exe") or shutil.which("powershell")
        if powershell:
            environment = os.environ.copy()
            environment["KOCOTREE_SCAN_ROOT"] = str(root)
            environment["KOCOTREE_SCAN_TEXT"] = name_contains
            command = (
                "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; "
                "$text=$env:KOCOTREE_SCAN_TEXT; "
                "$filter=if($text){'*'+[WildcardPattern]::Escape($text)+'*'}else{'*'}; "
                "Get-ChildItem -LiteralPath $env:KOCOTREE_SCAN_ROOT -Recurse -File -Filter $filter "
                "| ForEach-Object {$_.FullName}"
            )
            try:
                result = subprocess.run(
                    [powershell, "-NoProfile", "-NonInteractive", "-Command", command],
                    check=False,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=60,
                    env=environment,
                )
                if result.returncode == 0:
                    return sorted(
                        (
                            Path(line.strip()) for line in result.stdout.splitlines()
                            if line.strip() and Path(line.strip()).suffix.casefold() in normalized_suffixes
                        ),
                        key=lambda path: path.as_posix().casefold(),
                    )
                logger.warning("PowerShell 文件枚举失败，使用 Python 回退：%s", result.stderr.strip())
            except (OSError, subprocess.SubprocessError) as exc:
                logger.warning("PowerShell 文件枚举异常，使用 Python 回退：%s", exc)
    lowered = name_contains.casefold()
    return sorted(
        (
            path for path in root.rglob("*")
            if path.is_file()
            and path.suffix.casefold() in normalized_suffixes
            and (not lowered or lowered in path.name.casefold())
        ),
        key=lambda path: path.as_posix().casefold(),
    )
