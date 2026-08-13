from __future__ import annotations

from pathlib import Path

from common import ensure_dir, add_risk
from common.color_naming import color_output_name
from common.detail_page_slice import scale_detail_pages
from common.image_resize_compress import process_jpg_canvas
from common.scan_source_pack import get_image_group
from common.transparent_image_fit import process_vip_transparent_image


平台 = "唯品会"


def derive(
    source_root: Path,
    tmall_dir: Path,
    output_root: Path,
    report: dict,
    color_names: dict[Path, str],
) -> Path:
    """生成唯品会图片。

    功能说明：生成主图、颜色命名透明图和详情页。
    参数：
        source_root：产品素材根目录。
        tmall_dir：天猫通用版目录。
        output_root：产品输出目录。
        report：完整处理报告。
        color_names：透明图源路径到 SKU 颜色名称的映射。
    返回值：
        唯品会输出目录。
    """
    platform_dir = ensure_dir(output_root / 平台)
    main_sources = get_image_group(source_root, "主图1440")
    if not main_sources:
        main_sources = get_image_group(source_root, "主图800")
        if main_sources:
            add_risk(report, "唯品会未找到主图1440，已使用主图800放大生成1200主图")
    main_dir = ensure_dir(platform_dir / "1200主图")
    for source in main_sources:
        process_jpg_canvas(source, main_dir / f"{source.stem}.jpg", (1200, 1200), 500 * 1024, report, 平台, "1200主图")
    transparent_dir = ensure_dir(platform_dir / "1200透明图")
    for source in get_image_group(source_root, "透明图"):
        process_vip_transparent_image(
            source,
            transparent_dir / color_output_name(source, color_names, ".png"),
            1200,
            500 * 1024,
            report,
            平台,
            "1200透明图",
        )
    scale_detail_pages(tmall_dir / "790详情页", platform_dir / "750详情页", 750, 1600, 500 * 1024, report, 平台, "750详情页")
    return platform_dir
