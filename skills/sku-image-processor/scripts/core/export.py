"""最终交付图片导出。"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from core.utils import get_logger

logger = get_logger(__name__)


def export_final_images(final_dir: Path, output_dir: Path) -> dict[str, Any]:
    """把批次 final 目录复制到用户指定的交付目录。

    参数:
        final_dir: 项目内部最终图片目录。
        output_dir: 用户指定的外部交付目录，必须不存在或为空。
    返回值:
        导出状态、目标路径和图片数量。
    """
    source = final_dir.resolve()
    destination = output_dir.resolve()
    if not source.exists():
        raise FileNotFoundError(f"最终图片目录不存在: {source}")
    image_paths = [
        path for path in source.rglob("*")
        if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png"}
    ]
    if not image_paths:
        raise FileNotFoundError(f"最终图片目录中没有可导出的图片: {source}")
    if destination == source or destination in source.parents or source in destination.parents:
        raise ValueError("外部交付目录不能与项目内部 final 目录相同或互相包含")
    if destination.exists():
        if not destination.is_dir() or any(destination.iterdir()):
            raise FileExistsError(f"外部交付目录必须不存在或为空: {destination}")
        destination.rmdir()

    logger.info("开始导出最终图片: %s -> %s", source, destination)
    shutil.copytree(source, destination)
    report = {
        "status": "pass",
        "source": str(source),
        "output": str(destination),
        "images": len(image_paths),
    }
    logger.info("最终图片导出完成: %s（%d 张）", destination, len(image_paths))
    return report
