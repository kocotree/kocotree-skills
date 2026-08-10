from __future__ import annotations

import hashlib
import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from .utils import ensure_dir


logger = logging.getLogger(__name__)
DEFAULT_BARTENDER_ROOT = Path(r"C:\Program Files\Seagull\BarTender 2021")


@dataclass(frozen=True)
class SourceFingerprint:
    """保存 BarTender 源文件的保护指纹。"""

    size: int
    modified_ns: int
    sha256: str


def fingerprint(path: Path) -> SourceFingerprint:
    """计算源文件大小、修改时间和 SHA-256。"""
    stat = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return SourceFingerprint(stat.st_size, stat.st_mtime_ns, digest.hexdigest())


def find_bartender_resources(root: Path | None = None) -> tuple[Path, Path]:
    """定位 BarTender 程序和 Print SDK 程序集。

    参数：
        root：可选的 BarTender 安装目录。
    返回值：
        BarTender 可执行文件和 SDK 程序集路径。
    """
    install_root = root or DEFAULT_BARTENDER_ROOT
    executable = install_root / "BarTend.exe"
    assembly = install_root / "SDK" / "Assemblies" / "Seagull.BarTender.Print.dll"
    if not executable.is_file():
        raise RuntimeError(f"BarTender 程序缺失：{executable}")
    if not assembly.is_file():
        raise RuntimeError(f"BarTender Print SDK 缺失：{assembly}")
    return executable, assembly


def export_bartender_image(
    source: Path,
    output: Path,
    bartender_root: Path | None = None,
    width: int = 2400,
    height: int = 2400,
    timeout: int = 120,
) -> Path:
    """通过 BarTender Print SDK 只读导出合格证 PNG。

    参数：
        source：现有 `.btw` 文件。
        output：导出 PNG 路径。
        bartender_root：可选的 BarTender 安装目录。
        width：导出分辨率宽度。
        height：导出分辨率高度。
        timeout：外部导出的超时秒数。
    返回值：
        已验证的 PNG 路径。
    """
    if source.suffix.lower() != ".btw" or not source.is_file():
        raise RuntimeError(f"BarTender 源文件无效：{source}")
    _, assembly = find_bartender_resources(bartender_root)
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if not powershell:
        raise RuntimeError("未找到 Windows PowerShell，无法调用 BarTender Print SDK")
    script = Path(__file__).with_name("bartender_export.ps1")
    ensure_dir(output.parent)
    before = fingerprint(source)
    logger.info("开始导出 BarTender source=%r output=%r", str(source), str(output))
    result = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            "-Source",
            str(source),
            "-Output",
            str(output),
            "-Assembly",
            str(assembly),
            "-Width",
            str(width),
            "-Height",
            str(height),
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    after = fingerprint(source)
    if before != after:
        raise RuntimeError(f"BarTender 源文件在导出期间发生变化：{source}")
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"BarTender 导出失败：{detail[:1000] or result.returncode}")
    if not output.is_file():
        raise RuntimeError(f"BarTender 未生成导出图片：{output}")
    try:
        with Image.open(output) as image:
            image.verify()
    except Exception as exc:
        raise RuntimeError(f"BarTender 导出图片无效：{output}，{exc}") from exc
    logger.info("BarTender 导出完成 output=%r", str(output))
    return output
