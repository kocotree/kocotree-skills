from __future__ import annotations

from pathlib import Path

from common import ensure_dir, copy_file_original, add_review_suggestion
from detail_page_slice import collect_detail_sources, generate_sequential_detail_pages
from image_resize_compress import process_jpg_original_or_compress, process_png_original_or_compress
from scan_source_pack import 源目录规则, get_image_group, get_sku800, get_sku1440


平台 = "天猫通用版"


def build(source_root: Path, output_root: Path, report: dict) -> Path:
    platform_dir = ensure_dir(output_root / 平台)

    _batch_jpg(get_image_group(source_root, "主图800"), platform_dir / "主图" / "800主图", "主图\\800主图", report)
    _batch_jpg(get_image_group(source_root, "主图750"), platform_dir / "主图" / "750 1000主图", "主图\\750 1000主图", report)
    _batch_jpg(get_sku800(source_root), platform_dir / "sku" / "800", "sku\\800", report)
    _batch_jpg(get_sku1440(source_root), platform_dir / "sku" / "1440", "sku\\1440", report)
    _batch_jpg(get_image_group(source_root, "白底图"), platform_dir / "800白底图", "800白底图", report)
    _batch_png(get_image_group(source_root, "透明图"), platform_dir / "800透明图", "800透明图", report)
    _copy_material_images(get_image_group(source_root, "素材图", recursive=True), source_root / 源目录规则["素材图"], platform_dir / "素材图", report)

    detail_dir = platform_dir / "790详情页"
    detail_outputs = generate_sequential_detail_pages(collect_detail_sources(source_root), detail_dir, 790, 1600, 500 * 1024, report, 平台, "790详情页")
    if detail_outputs:
        add_review_suggestion(
            report,
            "天猫790详情页模块完整性判断",
            detail_outputs,
            "脚本不调用大模型；需要Agent检查详情页是否切断完整模块、顺序混乱、异常空白或重复拼接。",
        )
    return platform_dir


def _batch_jpg(sources: list[Path], output_dir: Path, usage: str, report: dict) -> None:
    ensure_dir(output_dir)
    for source in sources:
        process_jpg_original_or_compress(source, output_dir / f"{source.stem}.jpg", 500 * 1024, report, 平台, usage)


def _batch_png(sources: list[Path], output_dir: Path, usage: str, report: dict) -> None:
    ensure_dir(output_dir)
    for source in sources:
        process_png_original_or_compress(source, output_dir / f"{source.stem}.png", 500 * 1024, report, 平台, usage)


def _copy_material_images(sources: list[Path], source_base: Path, output_dir: Path, report: dict) -> None:
    ensure_dir(output_dir)
    for source in sources:
        try:
            relative = source.relative_to(source_base)
        except ValueError:
            relative = Path(source.name)
        copy_file_original(source, output_dir / relative, report, 平台, "素材图")
