from __future__ import annotations

import logging
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .utils import 平台目录名, ensure_dir


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SourceCopy:
    """保存源目录、本地副本和输入类型。"""

    source: Path
    working_copy: Path
    kind: str


def detect_source_kind(source: Path) -> str:
    """识别标准数据包、产品目录、批处理目录或成品包。"""
    if source.name == "数据包":
        return "data-pack"
    if (source / "数据包").is_dir():
        return "product"
    platform_count = sum((source / name).is_dir() for name in 平台目录名.values())
    if platform_count >= 2:
        return "finished-pack"
    children = [child for child in source.iterdir() if child.is_dir()] if source.is_dir() else []
    if children and all((child / "数据包").is_dir() for child in children):
        return "batch"
    return "unknown"


def create_local_copy(source: Path, temp_root: Path | None = None) -> SourceCopy:
    """创建原始数据包的本地工作副本。

    参数：
        source：源数据包或产品目录。
        temp_root：可选的本地临时根目录。
    返回值：
        源路径、工作副本和输入类型。
    """
    kind = detect_source_kind(source)
    if kind not in {"data-pack", "product"}:
        raise RuntimeError(f"当前输入不适合创建原始包工作副本：{source}")
    if temp_root:
        ensure_dir(temp_root)
        task_root = Path(tempfile.mkdtemp(prefix="kocotree-pack-", dir=temp_root))
    else:
        task_root = Path(tempfile.mkdtemp(prefix="kocotree-pack-"))
    target = task_root / source.name
    logger.info("开始创建本地工作副本 source=%r target=%r", str(source), str(target))
    shutil.copytree(source, target, copy_function=shutil.copy2)
    logger.info("本地工作副本创建完成 target=%r", str(target))
    return SourceCopy(source, target, kind)


def create_modified_copy(source: Path, output_root: Path | None = None) -> SourceCopy:
    """为多平台成品包创建独立修改副本。

    参数：
        source：多平台成品包目录。
        output_root：可选的副本父目录。
    返回值：
        源路径、修改副本和输入类型。
    """
    if detect_source_kind(source) != "finished-pack":
        raise RuntimeError(f"当前输入不是多平台成品包：{source}")
    parent = output_root or source.parent
    ensure_dir(parent)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = parent / f"{source.name}_面料修正版_{timestamp}"
    shutil.copytree(source, target, copy_function=shutil.copy2)
    logger.info("成品包修改副本创建完成 source=%r target=%r", str(source), str(target))
    return SourceCopy(source, target, "finished-pack")


def cleanup_local_copy(copy: SourceCopy) -> bool:
    """安全清理本模块创建的系统临时工作目录。

    参数：
        copy：`create_local_copy` 返回的工作副本信息。
    返回值：
        成功清理返回 True，不属于系统临时目录时返回 False。
    """
    task_root = copy.working_copy.parent.resolve()
    temp_root = Path(tempfile.gettempdir()).resolve()
    try:
        task_root.relative_to(temp_root)
    except ValueError:
        logger.warning("工作副本不在系统临时目录，保留文件：%s", task_root)
        return False
    if not task_root.name.startswith("kocotree-pack-"):
        logger.warning("工作副本目录前缀不匹配，保留文件：%s", task_root)
        return False
    shutil.rmtree(task_root)
    logger.info("本地工作副本已清理 target=%r", str(task_root))
    return True
