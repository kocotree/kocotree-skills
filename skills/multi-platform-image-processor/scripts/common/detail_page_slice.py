from __future__ import annotations

import logging
import math
from pathlib import Path

from PIL import Image

from .utils import list_images, ensure_dir, add_failure, add_risk, add_warning
from .image_resize_compress import open_image, save_jpg_under


logger = logging.getLogger(__name__)


def collect_detail_sources(source_root: Path) -> list[Path]:
    """按已验证的详情页结构收集源图片。

    功能说明：平铺模式读取静态目录中的直接图片；上/下模式按“上”后
    “下”的顺序合并图片。混合或不完整结构会直接报错。

    参数：
        source_root：数据包根目录。
    返回值：
        按详情页展示顺序排列的源图片路径。
    """
    static = source_root / "详情" / "静态"
    upper = static / "上"
    lower = static / "下"
    direct_images = list_images(static)
    upper_exists = upper.is_dir()
    lower_exists = lower.is_dir()

    if direct_images and (upper_exists or lower_exists):
        logger.error(
            "详情页源图片收集失败：平铺与上/下结构混用 root=%r",
            str(static),
            extra={
                "stage": "详情页",
                "event": "详情源图收集",
                "status": "failed",
            },
        )
        raise ValueError("详情页平铺图片不能与上/下目录同时存在")

    if direct_images:
        logger.info(
            "详情页源图片收集完成 mode=flat count=%d",
            len(direct_images),
            extra={
                "stage": "详情页",
                "event": "详情源图收集",
                "status": "success",
            },
        )
        return direct_images

    upper_images = list_images(upper) if upper_exists else []
    lower_images = list_images(lower) if lower_exists else []
    if upper_exists and lower_exists and upper_images and lower_images:
        sources = upper_images + lower_images
        logger.info(
            "详情页源图片收集完成 mode=upper-lower upper_count=%d lower_count=%d total=%d",
            len(upper_images),
            len(lower_images),
            len(sources),
            extra={
                "stage": "详情页",
                "event": "详情源图收集",
                "status": "success",
            },
        )
        return sources

    logger.error(
        "详情页源图片收集失败：上/下结构不完整 root=%r upper_count=%d lower_count=%d",
        str(static),
        len(upper_images),
        len(lower_images),
        extra={
            "stage": "详情页",
            "event": "详情源图收集",
            "status": "failed",
        },
    )
    raise ValueError("详情页必须使用平铺结构或完整且非空的上/下结构")


def generate_sequential_detail_pages(
    sources: list[Path],
    output_dir: Path,
    width: int,
    max_height: int,
    max_bytes: int,
    report: dict,
    platform: str,
    usage: str,
    start_number: int = 601,
) -> list[Path]:
    ensure_dir(output_dir)
    outputs: list[Path] = []
    number = start_number
    for source in sources:
        try:
            image = open_image(source)
            ratio = width / image.width
            resized = image.resize((width, max(1, round(image.height * ratio))), Image.Resampling.LANCZOS)
            pieces = split_by_height(resized, max_height)
            if len(pieces) > 1:
                add_risk(report, "详情页单图超过高度限制，已自动切分，可能切到完整模块", 源文件=str(source), 切片数=len(pieces))
            for piece in pieces:
                output = output_dir / f"{number}.jpg"
                saved = save_jpg_under(piece, output, max_bytes, report, source, platform, usage, [f"缩放到宽{width}px", f"高度限制{max_height}px"])
                if saved:
                    outputs.append(saved)
                    number += 1
        except Exception as exc:
            add_failure(report, "生成详情页失败", 源文件=str(source), 错误=str(exc))
    return outputs


def scale_detail_pages_from_master(
    master_dir: Path,
    output_dir: Path,
    width: int,
    max_height: int,
    max_bytes: int,
    report: dict,
    platform: str,
    usage: str,
) -> list[Path]:
    return generate_sequential_detail_pages(list_images(master_dir), output_dir, width, max_height, max_bytes, report, platform, usage)


def merge_long_detail_slices(
    sources: list[Path],
    output_dir: Path,
    width: int,
    max_height: int,
    max_count: int,
    max_bytes: int,
    report: dict,
    platform: str,
    usage: str,
) -> list[Path]:
    ensure_dir(output_dir)
    resized_images: list[Image.Image] = []
    for source in sources:
        try:
            image = open_image(source)
            ratio = width / image.width
            resized_images.append(image.resize((width, max(1, round(image.height * ratio))), Image.Resampling.LANCZOS))
        except Exception as exc:
            add_failure(report, "读取长切片详情页来源失败", 源文件=str(source), 错误=str(exc))
    groups: list[list[Image.Image]] = []
    current: list[Image.Image] = []
    current_h = 0
    for image in resized_images:
        if current and current_h + image.height > max_height:
            groups.append(current)
            current = []
            current_h = 0
        if image.height > max_height:
            parts = split_by_height(image, max_height)
            add_risk(report, "详情页单个模块超过长切片高度限制，已切分", 高度=image.height, 限制=max_height)
            for part in parts:
                groups.append([part])
            continue
        current.append(image)
        current_h += image.height
    if current:
        groups.append(current)
    if len(groups) > max_count:
        add_warning(report, "蜂享家＋爱库存详情页数量超过限制，已尽量输出", 数量=len(groups), 限制=max_count)
    outputs: list[Path] = []
    for idx, group in enumerate(groups, start=1):
        height = sum(img.height for img in group)
        canvas = Image.new("RGB", (width, height), (255, 255, 255))
        y = 0
        for img in group:
            canvas.paste(img.convert("RGB"), (0, y))
            y += img.height
        output = output_dir / f"详情图-{idx:02d}.jpg"
        saved = save_jpg_under(canvas, output, max_bytes, report, None, platform, usage, [f"合成长切片宽{width}px", f"高度限制{max_height}px"])
        if saved:
            outputs.append(saved)
    return outputs


def split_by_height(image: Image.Image, max_height: int) -> list[Image.Image]:
    if image.height <= max_height:
        return [image]
    parts = []
    count = math.ceil(image.height / max_height)
    for idx in range(count):
        top = idx * max_height
        bottom = min(image.height, (idx + 1) * max_height)
        parts.append(image.crop((0, top, image.width, bottom)))
    return parts
