from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import logging
from pathlib import Path

from common import add_review_suggestion, ensure_dir
from common.color_naming import color_output_name
from common.image_resize_compress import process_jpg_original_or_compress, process_png_original_or_compress
from common.logo_overlay import find_logo, overlay_logo
from common.scan_source_pack import get_image_group, get_sku800_recursive, resolve_source_path
from common.text_removal import ensure_text2image_ready, get_text_removal_temp_dir, process_offsite_sku_text_removal, prune_temp_images


平台 = "站外通用版"
SKU_TEXT_REMOVAL_CONCURRENCY = 10
logger = logging.getLogger(__name__)


def _select_offsite_sku_sources(source_root: Path) -> list[Path]:
    """选择站外通用版需要去字的 SKU 图片。

    功能说明：存在“无赠品”SKU 分支时仅返回该分支；普通 SKU 结构返回全部 800 图。
    参数：
        source_root：产品素材根目录。
    返回值：
        站外通用版需要处理的 SKU 图片列表。
    """
    sources = get_sku800_recursive(source_root)
    sku_base = resolve_source_path(source_root, "SKU")
    no_gift_sources: list[Path] = []
    for source in sources:
        try:
            directory_parts = source.relative_to(sku_base).parent.parts
        except ValueError:
            directory_parts = source.parent.parts
        if any("无赠品" in part.replace(" ", "") for part in directory_parts):
            no_gift_sources.append(source)
    if not no_gift_sources:
        logger.info("站外SKU使用全部800图 count=%d", len(sources))
        return sources
    logger.info(
        "站外SKU仅使用无赠品分支 selected=%d skipped=%d",
        len(no_gift_sources),
        len(sources) - len(no_gift_sources),
    )
    return no_gift_sources


def derive(
    source_root: Path,
    template_root: Path | None,
    output_root: Path,
    report: dict,
    color_names: dict[Path, str],
) -> Path:
    """生成站外通用版。

    功能说明：生成去字 SKU、颜色命名白底图、Logo 图、透明图和素材图。
    参数：
        source_root：产品素材根目录。
        template_root：包含站外 Logo 的平台模板目录。
        output_root：产品输出目录。
        report：完整处理报告。
        color_names：白底图、透明图源路径到 SKU 颜色名称的映射。
    返回值：
        站外通用版输出目录。
    """
    platform_dir = ensure_dir(output_root / 平台)
    sku_outputs = []
    sku_dir = ensure_dir(platform_dir / "sku")
    sku_sources = _select_offsite_sku_sources(source_root)
    if sku_sources:
        ready, ready_msg = ensure_text2image_ready()
        if not ready:
            from common import add_failure
            add_failure(report, "text2image 不可用，跳过站外SKU去字", 原因=ready_msg)
            sku_sources = []
    if sku_sources:
        used_output_paths: set[Path] = set()
        sku_base = resolve_source_path(source_root, "SKU")
        sku_tasks = [(source, _sku_output_path(source, sku_base, sku_dir, used_output_paths)) for source in sku_sources]
        with ThreadPoolExecutor(max_workers=SKU_TEXT_REMOVAL_CONCURRENCY) as executor:
            futures = [
                executor.submit(
                    process_offsite_sku_text_removal,
                    source,
                    output,
                    500 * 1024,
                    report,
                    平台,
                    False,
                )
                for source, output in sku_tasks
            ]
            for future in futures:
                saved = future.result()
                if saved:
                    sku_outputs.append(saved)
        prune_temp_images(get_text_removal_temp_dir())
    if sku_outputs:
        add_review_suggestion(
            report,
            "站外SKU去字质量判断",
            sku_outputs,
            "已对右侧商品卡片纵向裁片调用 text2image 去字；需要Agent按原尺寸逐张对比原图与输出图，确认彩色标签文字已去除，标签轮廓、卡片、商品图、人物、背景和图片四角没有变化，也没有新增色块或图形。",
        )

    _batch_color_jpg(
        get_image_group(source_root, "白底图"),
        platform_dir / "白底图",
        "白底图",
        report,
        color_names,
    )
    logo = find_logo(template_root)
    logo_dir = ensure_dir(platform_dir / "白底图＋logo")
    for source in get_image_group(source_root, "白底图"):
        overlay_logo(
            source,
            logo,
            logo_dir / color_output_name(source, color_names, ".jpg"),
            500 * 1024,
            report,
            平台,
            "白底图＋logo",
        )
    _batch_color_png(
        get_image_group(source_root, "透明图"),
        platform_dir / "透明图",
        "透明图",
        report,
        color_names,
    )
    material_dir = ensure_dir(platform_dir / "素材图")
    material_base = resolve_source_path(source_root, "素材图")
    for source in get_image_group(source_root, "素材图", recursive=True):
        try:
            relative = source.relative_to(material_base)
        except ValueError:
            relative = Path(source.name)
        out = material_dir / relative
        ensure_dir(out.parent)
        if source.suffix.lower() in (".png",):
            process_png_original_or_compress(source, out.with_suffix(".png"), 500 * 1024, report, 平台, "素材图")
        else:
            process_jpg_original_or_compress(source, out.with_suffix(".jpg"), 500 * 1024, report, 平台, "素材图")
    ensure_dir(platform_dir / "详情页")
    ensure_dir(platform_dir / "主图")
    return platform_dir


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


def _batch_color_png(
    sources: list[Path],
    output_dir: Path,
    usage: str,
    report: dict,
    color_names: dict[Path, str],
) -> None:
    ensure_dir(output_dir)
    for source in sources:
        process_png_original_or_compress(
            source,
            output_dir / color_output_name(source, color_names, ".png"),
            500 * 1024,
            report,
            平台,
            usage,
        )


def _unique_output_path(path: Path, used: set[Path]) -> Path:
    candidate = path
    idx = 2
    while candidate in used:
        candidate = path.with_name(f"{path.stem}_{idx}{path.suffix}")
        idx += 1
    used.add(candidate)
    return candidate


def _sku_output_path(source: Path, source_base: Path, output_dir: Path, used: set[Path]) -> Path:
    try:
        relative = source.relative_to(source_base)
    except ValueError:
        relative = Path(source.name)
    name_parts = [*relative.parent.parts, relative.stem]
    safe_name = "_".join(part for part in name_parts if part)
    return _unique_output_path(output_dir / f"{safe_name}.jpg", used)
