from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from common import ensure_dir, copy_file_original, add_failure, add_review_suggestion
from common.detail_page_slice import generate_sequential_detail_pages, prepare_ordered_detail_sources
from common.image_resize_compress import process_jpg_original_or_compress, process_png_original_or_compress
from common.scan_source_pack import 源目录规则, get_image_group, get_sku800, get_sku1440


平台 = "天猫通用版"


def build(source_root: Path, output_root: Path, report: dict, detail_plan: Path | None = None) -> Path:
    """生成天猫通用版并建立六平台详情页母版。

    参数：
        source_root：已验证的产品数据包根目录。
        output_root：六平台输出根目录。
        report：用于记录图片处理与异常的报告。
        detail_plan：Agent 视觉检查生成的详情模块计划路径。
    返回值：
        天猫通用版输出目录路径。
    """
    platform_dir = ensure_dir(output_root / 平台)

    _batch_jpg(get_image_group(source_root, "主图800"), platform_dir / "主图" / "800主图", "主图\\800主图", report)
    _batch_jpg(get_image_group(source_root, "主图750"), platform_dir / "主图" / "750 1000主图", "主图\\750 1000主图", report)
    _batch_jpg(get_sku800(source_root), platform_dir / "sku" / "800", "sku\\800", report)
    _batch_jpg(get_sku1440(source_root), platform_dir / "sku" / "1440", "sku\\1440", report)
    _batch_jpg(get_image_group(source_root, "白底图"), platform_dir / "800白底图", "800白底图", report)
    _batch_png(get_image_group(source_root, "透明图"), platform_dir / "800透明图", "800透明图", report)
    _copy_material_images(get_image_group(source_root, "素材图", recursive=True), source_root / 源目录规则["素材图"], platform_dir / "素材图", report)

    detail_dir = platform_dir / "790详情页"
    detail_outputs: list[Path] = []
    try:
        if detail_plan is None:
            raise RuntimeError("缺少 Agent 详情页模块计划")
        with TemporaryDirectory(prefix="detail-modules-", dir=output_root) as staging_value:
            detail_sources = prepare_ordered_detail_sources(
                source_root,
                detail_plan,
                Path(staging_value),
                report,
            )
            detail_outputs = generate_sequential_detail_pages(
                detail_sources,
                detail_dir,
                790,
                1600,
                500 * 1024,
                report,
                平台,
                "790详情页",
            )
    except Exception as exc:
        add_failure(report, "详情页模块检查与排序失败", 错误=str(exc))
    if detail_outputs:
        add_review_suggestion(
            report,
            "天猫790详情页最终视觉复核",
            detail_outputs,
            "按原尺寸确认必需模块齐全、顺序正确，图标卡片边框与圆角完整。",
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
        out = output_dir / relative
        ensure_dir(out.parent)
        if source.suffix.lower() in (".png",):
            process_png_original_or_compress(source, out.with_suffix(".png"), 500 * 1024, report, 平台, "素材图")
        else:
            process_jpg_original_or_compress(source, out.with_suffix(".jpg"), 500 * 1024, report, 平台, "素材图")
