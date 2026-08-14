from __future__ import annotations

from pathlib import Path

from common import ensure_dir, add_review_suggestion, list_images
from common.color_naming import color_output_name
from common.detail_page_slice import merge_long_detail_slices
from common.image_resize_compress import process_jpg_original_or_compress
from common.scan_source_pack import get_image_group, get_sku800_recursive, resolve_sku_root


平台 = "蜂享家＋爱库存"


def derive(
    source_root: Path,
    tmall_dir: Path,
    output_root: Path,
    report: dict,
    color_names: dict[Path, str],
) -> Path:
    """生成蜂享家＋爱库存图片。

    功能说明：生成主图、SKU、颜色命名白底图和长切片详情页。
    参数：
        source_root：产品素材根目录。
        tmall_dir：天猫通用版目录。
        output_root：产品输出目录。
        report：完整处理报告。
        color_names：白底图源路径到 SKU 颜色名称的映射。
    返回值：
        蜂享家＋爱库存输出目录。
    """
    platform_dir = ensure_dir(output_root / 平台)
    _batch_jpg(get_image_group(source_root, "主图800"), platform_dir / "800主图", "800主图", report)
    _copy_sku800_tree(source_root, platform_dir / "800sku", report)
    _batch_color_jpg(
        get_image_group(source_root, "白底图"),
        platform_dir / "800白底图",
        "800白底图",
        report,
        color_names,
    )
    detail_outputs = merge_long_detail_slices(
        list_images(tmall_dir / "790详情页"),
        platform_dir / "790详情页",
        790,
        4800,
        20,
        1024 * 1024,
        report,
        平台,
        "790详情页",
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


def _copy_sku800_tree(source_root: Path, output_dir: Path, report: dict) -> None:
    """复制 SKU 800 图并保留赠品分支。

    功能说明：标准 `SKU/800` 直接输出图片；嵌套赠品结构保留其相对目录。
    参数：
        source_root：产品素材根目录。
        output_dir：蜂享家与爱库存的 800 SKU 输出目录。
        report：完整处理报告。
    返回值：
        无。
    """
    sku_root = resolve_sku_root(source_root)
    ensure_dir(output_dir)
    for source in get_sku800_recursive(source_root):
        relative = source.relative_to(sku_root)
        if len(relative.parts) == 2 and relative.parts[0].casefold() == "800":
            relative = Path(relative.name)
        output = output_dir / relative.with_suffix(".jpg")
        ensure_dir(output.parent)
        process_jpg_original_or_compress(source, output, 500 * 1024, report, 平台, "800sku")


def _batch_color_jpg(
    sources: list[Path],
    output_dir: Path,
    usage: str,
    report: dict,
    color_names: dict[Path, str],
) -> None:
    ensure_dir(output_dir)
    for source in sources:
        process_jpg_original_or_compress(
            source,
            output_dir / color_output_name(source, color_names, ".jpg"),
            500 * 1024,
            report,
            平台,
            usage,
        )
