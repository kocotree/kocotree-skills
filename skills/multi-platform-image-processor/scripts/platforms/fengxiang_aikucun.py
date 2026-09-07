from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from common import ensure_dir, add_review_suggestion, list_images
from common.color_naming import color_output_relative_path
from common.color_text import prepare_color_overrides, rename_color_file
from common.detail_page_slice import (
    generate_sequential_detail_pages, merge_long_detail_slices, prepare_ordered_detail_sources,
)
from common.image_resize_compress import process_jpg_original_or_compress
from common.scan_source_pack import (
    get_combination_sku,
    get_image_group,
    get_sku800_recursive,
    resolve_sku_root,
    resolve_source_path,
)


平台 = "蜂享家＋爱库存"


def derive(
    source_root: Path,
    tmall_dir: Path,
    output_root: Path,
    report: dict,
    color_names: dict[Path, str],
    color_text_plan: list[dict] | None = None,
    detail_plan: Path | None = None,
    detail_overrides: dict[Path, Path] | None = None,
) -> Path:
    """生成蜂享家＋爱库存图片。

    功能说明：生成主图、SKU、颜色命名白底图和长切片详情页。
    参数：
        source_root：产品素材根目录。
        tmall_dir：天猫通用版目录。
        output_root：产品输出目录。
        report：完整处理报告。
        color_names：白底图源路径到 SKU 颜色名称的映射。
        color_text_plan：目标平台颜色名称的源图文字定位项。
        detail_plan：共享的详情排序、切分计划。
        detail_overrides：共享的无损面料修正映射。
    返回值：
        蜂享家＋爱库存输出目录。
    """
    platform_dir = ensure_dir(output_root / 平台)
    _batch_jpg(get_image_group(source_root, "主图800"), platform_dir / "800主图", "800主图", report)
    _batch_color_jpg(
        get_image_group(source_root, "白底图", recursive=True),
        resolve_source_path(source_root, "白底图"),
        platform_dir / "800白底图",
        "800白底图",
        report,
        color_names,
    )
    with TemporaryDirectory(prefix="platform-colors-") as temporary:
        staging = Path(temporary)
        overrides = prepare_color_overrides(source_root, color_text_plan or [], staging / "颜色", detail_overrides)
        _copy_sku800_tree(source_root, platform_dir / "800sku", report, overrides)
        detail_sources = list_images(tmall_dir / "790详情页")
        if color_text_plan:
            if detail_plan is None:
                raise ValueError("颜色改字需要共享详情计划，以保持目标平台的详情顺序")
            ordered = prepare_ordered_detail_sources(source_root, detail_plan, staging / "模块", report, overrides)
            detail_sources = generate_sequential_detail_pages(
                ordered, staging / "详情", 790, 1600, 500 * 1024, report, 平台, "颜色修改临时详情",
            )
        detail_outputs = merge_long_detail_slices(
            detail_sources, platform_dir / "790详情页", 790, 4800, 20,
            1024 * 1024, report, 平台, "790详情页",
        )
    if detail_outputs:
        add_review_suggestion(
            report,
            "蜂享家＋爱库存详情页长切片模块完整性判断",
            detail_outputs,
            "脚本不调用大模型；需要Agent检查长切片是否切碎完整模块，是否有异常拼接、重复、空白或顺序混乱。",
        )
    return platform_dir


def _batch_jpg(sources: list[Path], output_dir: Path, usage: str, report: dict) -> None:
    ensure_dir(output_dir)
    for source in sources:
        process_jpg_original_or_compress(source, output_dir / f"{source.stem}.jpg", 500 * 1024, report, 平台, usage)


def _copy_sku800_tree(source_root: Path, output_dir: Path, report: dict,
                      overrides: dict[Path, Path] | None = None) -> None:
    """复制 SKU 800 图、赠品分支和组合 SKU。

    功能说明：标准 `SKU/800` 直接输出图片；赠品和 `SKU组合` 保留相对目录。
    参数：
        source_root：产品素材根目录。
        output_dir：蜂享家与爱库存的 800 SKU 输出目录。
        report：完整处理报告。
        overrides：原 SKU 到颜色改字临时图的映射。
    返回值：
        无。
    """
    sku_root = resolve_sku_root(source_root)
    ensure_dir(output_dir)
    sources = [*get_sku800_recursive(source_root), *get_combination_sku(source_root)]
    for source in dict.fromkeys(sources):
        relative = source.relative_to(sku_root)
        if len(relative.parts) == 2 and relative.parts[0].casefold() == "800":
            relative = Path(relative.name)
        output = output_dir / rename_color_file(relative.with_suffix(".jpg"))
        ensure_dir(output.parent)
        process_jpg_original_or_compress(
            (overrides or {}).get(source.resolve(), source), output, 500 * 1024, report, 平台, "800sku",
        )
        if output.name != relative.with_suffix(".jpg").name and source.resolve() not in (overrides or {}):
            add_review_suggestion(
                report, "蜂享家＋爱库存颜色文字核对", [output],
                "文件名已按颜色规则替换；检查图片中是否仍有原颜色文字，存在时补充源图改字定位后生成。",
            )


def _batch_color_jpg(
    sources: list[Path],
    source_base: Path,
    output_dir: Path,
    usage: str,
    report: dict,
    color_names: dict[Path, str],
) -> None:
    ensure_dir(output_dir)
    for source in sources:
        relative = color_output_relative_path(source, source_base, color_names, ".jpg")
        output = output_dir / relative
        ensure_dir(output.parent)
        process_jpg_original_or_compress(
            source,
            output,
            500 * 1024,
            report,
            平台,
            usage,
        )
