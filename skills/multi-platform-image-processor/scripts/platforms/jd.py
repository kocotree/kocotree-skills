from __future__ import annotations

from pathlib import Path

from common import list_images, ensure_dir
from common.detail_page_slice import scale_detail_pages_from_master
from common.image_resize_compress import process_jpg_original_or_compress
from common.scan_source_pack import get_image_group, get_sku800
from common.transparent_image_fit import process_square_transparent_image


平台 = "京东"


def derive(source_root: Path, tmall_dir: Path, output_root: Path, report: dict) -> Path:
    """从源素材和天猫母版生成京东平台图片包。

    参数：
        source_root: 源数据包根目录，用于读取主图、SKU 和透明图。
        tmall_dir: 天猫通用版输出目录，用于读取 790px 宽详情页母版。
        output_root: 全平台输出根目录，京东目录将在此目录下创建。
        report: 处理报告，记录图片结果、风险、警告和失败项。

    返回值：
        京东平台输出目录路径。
    """
    platform_dir = ensure_dir(output_root / 平台)
    _batch_jpg(get_image_group(source_root, "主图800"), platform_dir / "800主图", "800主图", report)
    _batch_jpg(get_image_group(source_root, "主图750"), platform_dir / "750主图", "750主图", report)
    _batch_jpg(get_sku800(source_root), platform_dir / "800sku", "800sku", report)
    transparent_dir = ensure_dir(platform_dir / "透明图")
    for source in get_image_group(source_root, "透明图"):
        process_square_transparent_image(source, transparent_dir / f"{source.stem}.png", 800, 500 * 1024, report, 平台, "透明图")
    scale_detail_pages_from_master(tmall_dir / "790详情页", platform_dir / "详情页", 790, 1600, 500 * 1024, report, 平台, "详情页")
    return platform_dir


def _batch_jpg(sources: list[Path], output_dir: Path, usage: str, report: dict) -> None:
    ensure_dir(output_dir)
    for source in sources:
        process_jpg_original_or_compress(source, output_dir / f"{source.stem}.jpg", 500 * 1024, report, 平台, usage)
