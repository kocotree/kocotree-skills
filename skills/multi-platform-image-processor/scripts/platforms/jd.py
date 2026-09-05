from __future__ import annotations

import logging
from pathlib import Path

from common import ensure_dir
from common.color_naming import color_output_relative_path
from common.detail_page_slice import scale_detail_pages
from common.image_resize_compress import process_jpg_canvas, process_jpg_original_or_compress
from common.scan_source_pack import get_image_group, resolve_source_path
from common.transparent_image_fit import process_square_transparent_image


平台 = "京东"
logger = logging.getLogger(__name__)


def derive(
    source_root: Path,
    tmall_dir: Path,
    platform_dir: Path,
    report: dict,
    color_names: dict[Path, str],
) -> Path:
    """从源素材和天猫已生成详情页生成京东平台图片包。

    参数：
        source_root: 源数据包根目录，用于读取主图和透明图。
        tmall_dir: 天猫通用版输出目录，用于读取 790px 宽详情页。
        platform_dir: 包含产品货号和名称的京东平台输出目录。
        report: 处理报告，记录图片结果、风险、警告和失败项。
        color_names: 白底图、透明图源路径到 SKU 颜色名称的映射。

    返回值：
        京东平台输出目录路径。
    """
    platform_dir = ensure_dir(platform_dir)
    _build_main_images(source_root, platform_dir, report)
    ensure_dir(platform_dir / "800sku")
    transparent_dir = ensure_dir(platform_dir / "透明图")
    transparent_base = resolve_source_path(source_root, "透明图")
    for source in get_image_group(source_root, "透明图", recursive=True):
        relative = color_output_relative_path(source, transparent_base, color_names, ".png")
        output = transparent_dir / relative
        ensure_dir(output.parent)
        process_square_transparent_image(
            source,
            output,
            800,
            500 * 1024,
            report,
            平台,
            "透明图",
        )
    scale_detail_pages(tmall_dir / "790详情页", platform_dir / "详情页", 790, 1600, 500 * 1024, report, 平台, "详情页")
    return platform_dir


def _batch_jpg(sources: list[Path], output_dir: Path, usage: str, report: dict) -> None:
    ensure_dir(output_dir)
    for source in sources:
        process_jpg_original_or_compress(source, output_dir / f"{source.stem}.jpg", 500 * 1024, report, 平台, usage)


def _batch_jpg_canvas(
    sources: list[Path],
    output_dir: Path,
    size: tuple[int, int],
    usage: str,
    report: dict,
) -> None:
    ensure_dir(output_dir)
    for source in sources:
        process_jpg_canvas(
            source,
            output_dir / f"{source.stem}.jpg",
            size,
            500 * 1024,
            report,
            平台,
            usage,
        )


def _build_main_images(source_root: Path, platform_dir: Path, report: dict) -> None:
    """生成京东的两组主图。

    功能说明：输出 1440×1440 和 1080×1440 主图；1440 源图
    缺失时使用 800 主图生成，3:4 主图使用 750 主图生成。
    参数：
        source_root：产品数据包根目录。
        platform_dir：京东平台输出目录。
        report：完整处理报告。
    返回值：
        无。
    """
    sources_800 = get_image_group(source_root, "主图800")
    sources_1440 = get_image_group(source_root, "主图1440")
    if sources_1440:
        logger.info("京东1440主图使用原数据包素材 count=%d", len(sources_1440))
        _batch_jpg(sources_1440, platform_dir / "1440主图", "1440主图", report)
    else:
        logger.info("京东1440主图使用800主图生成 count=%d", len(sources_800))
        _batch_jpg_canvas(
            sources_800,
            platform_dir / "1440主图",
            (1440, 1440),
            "1440主图",
            report,
        )
    _batch_jpg_canvas(
        get_image_group(source_root, "主图750"),
        platform_dir / "1080主图",
        (1080, 1440),
        "1080主图",
        report,
    )
