from __future__ import annotations

import json
import logging
import math
from pathlib import Path

from PIL import Image

from .utils import list_images, ensure_dir, add_failure, add_risk, add_warning
from .image_resize_compress import open_image, save_jpg_under


logger = logging.getLogger(__name__)

详情模块顺序 = {
    "品牌背书": 1,
    "KV": 2,
    "适用图标": 3,
    "产品信息": 4,
    "尺码表": 5,
    "图标说明": 6,
    "卖点": 7,
    "面料": 7,
    "认证": 7,
    "模特": 7,
    "品牌故事": 7,
    "店铺": 7,
    "其他": 7,
}
必需详情模块 = ("品牌背书", "KV", "适用图标", "产品信息", "尺码表", "图标说明")


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


def prepare_ordered_detail_sources(
    source_root: Path,
    plan_path: Path,
    staging_dir: Path,
    report: dict,
    source_overrides: dict[Path, Path] | None = None,
) -> list[Path]:
    """根据 Agent 视觉计划校验、拆分并排序详情页模块。

    参数：
        source_root：数据包根目录。
        plan_path：Agent 生成的详情页模块 JSON 计划路径。
        staging_dir：需要拆分的模块临时输出目录。
        report：用于记录模块顺序和校验结果的报告。
        source_overrides：原始详情图到临时修正版的可选映射。
    返回值：
        按业务顺序排列的原图或水平拆分图路径。
    """
    if not plan_path.is_file():
        raise RuntimeError("缺少 Agent 详情页模块计划")
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"详情页模块计划无法读取：{exc}") from exc
    modules = plan.get("详情模块")
    if not isinstance(modules, list) or not modules:
        raise RuntimeError("详情页模块计划缺少“详情模块”列表")

    source_paths = collect_detail_sources(source_root)
    source_lookup = {path.resolve(): path for path in source_paths}
    parsed: list[dict] = []
    represented: dict[Path, list[tuple[int, int, int, int] | None]] = {}
    for index, item in enumerate(modules):
        if not isinstance(item, dict):
            raise RuntimeError(f"详情模块第 {index + 1} 项格式错误")
        module_type = str(item.get("类型", "")).strip()
        if module_type not in 详情模块顺序:
            raise RuntimeError(f"详情模块类型不受支持：{module_type or '空值'}")
        image_value = str(item.get("图片", "")).strip()
        candidate = Path(image_value)
        candidate = candidate if candidate.is_absolute() else source_root / candidate
        source = source_lookup.get(candidate.resolve())
        if source is None:
            raise RuntimeError(f"详情模块图片不在已验证的详情页源图中：{image_value}")
        box = _parse_module_box(item.get("区域"), source)
        represented.setdefault(source.resolve(), []).append(box)
        parsed.append({"类型": module_type, "源图": source, "区域": box, "原顺序": index})

    missing_sources = [str(path) for path in source_paths if path.resolve() not in represented]
    if missing_sources:
        raise RuntimeError(f"详情页模块计划未覆盖全部源图：{missing_sources}")
    for source in source_paths:
        _validate_source_coverage(source, represented[source.resolve()])

    present_types = {item["类型"] for item in parsed}
    missing_types = [name for name in 必需详情模块 if name not in present_types]
    if missing_types:
        raise RuntimeError(f"详情页缺少必需模块：{missing_types}")

    ordered = sorted(parsed, key=lambda item: (详情模块顺序[item["类型"]], item["原顺序"]))
    overrides = {
        source.resolve(): replacement
        for source, replacement in (source_overrides or {}).items()
    }
    ensure_dir(staging_dir)
    outputs: list[Path] = []
    sequence: list[dict] = []
    for index, item in enumerate(ordered, start=1):
        source = item["源图"]
        render_source = overrides.get(source.resolve(), source)
        box = item["区域"]
        output = render_source
        if box is not None:
            with Image.open(render_source) as image:
                output = staging_dir / f"{index:03d}.png"
                image.crop(box).save(output, "PNG")
        outputs.append(output)
        sequence.append(
            {
                "顺序": index,
                "类型": item["类型"],
                "源图": str(source),
                "面料已修正": render_source != source,
                "区域": list(box) if box is not None else [],
            }
        )
    report["详情页模块"] = {"计划路径": str(plan_path), "模块顺序": sequence}
    logger.info(
        "详情页模块准备完成 source_count=%d module_count=%d",
        len(source_paths),
        len(outputs),
        extra={"stage": "详情页", "event": "模块排序", "status": "success"},
    )
    return outputs


def _parse_module_box(value: object, source: Path) -> tuple[int, int, int, int] | None:
    """解析水平模块裁切区域。"""
    if value in (None, [], ""):
        return None
    if not isinstance(value, list) or len(value) != 4 or not all(isinstance(item, int) for item in value):
        raise RuntimeError(f"详情模块区域必须是四个整数：{source}")
    left, top, right, bottom = value
    with Image.open(source) as image:
        if left != 0 or right != image.width or not (0 <= top < bottom <= image.height):
            raise RuntimeError(f"详情模块只支持保留原宽的水平拆分：{source}")
    return left, top, right, bottom


def _validate_source_coverage(source: Path, boxes: list[tuple[int, int, int, int] | None]) -> None:
    """验证单张详情源图在模块计划中完整且不重叠。"""
    if boxes == [None]:
        return
    if not boxes or any(box is None for box in boxes):
        raise RuntimeError(f"详情源图不能同时使用整图和分段：{source}")
    ordered = sorted((box for box in boxes if box is not None), key=lambda box: box[1])
    with Image.open(source) as image:
        expected_top = 0
        for box in ordered:
            assert box is not None
            if box[1] != expected_top:
                raise RuntimeError(f"详情源图分段存在缺失或重叠：{source}")
            expected_top = box[3]
        if expected_top != image.height:
            raise RuntimeError(f"详情源图分段未覆盖到底部：{source}")


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
