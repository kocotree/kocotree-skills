from __future__ import annotations

from pathlib import Path

from common import ensure_dir, add_risk
from detail_page_slice import scale_detail_pages_from_master
from image_resize_compress import process_jpg_canvas
from scan_source_pack import get_image_group


平台 = "CBME"


def derive(source_root: Path, tmall_dir: Path, output_root: Path, report: dict) -> Path:
    platform_dir = ensure_dir(output_root / 平台)
    main_sources = get_image_group(source_root, "主图1440")
    if not main_sources:
        main_sources = get_image_group(source_root, "主图800")
        if main_sources:
            add_risk(report, "CBME未找到主图1440，已使用主图800降级生成750主图")
    main_dir = ensure_dir(platform_dir / "750主图")
    for source in main_sources:
        process_jpg_canvas(source, main_dir / f"{source.stem}.jpg", (750, 750), 500 * 1024, report, 平台, "750主图")
    scale_detail_pages_from_master(tmall_dir / "790详情页", platform_dir / "750详情页", 750, 1600, 500 * 1024, report, 平台, "750详情页")
    return platform_dir
