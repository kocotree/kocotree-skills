from __future__ import annotations

from pathlib import Path

from PIL import Image

from common import add_failure, add_risk
from image_resize_compress import open_image, save_png_under


def trim_transparent_edges(image: Image.Image, alpha_threshold: int = 8) -> Image.Image:
    rgba = image.convert("RGBA")
    alpha = rgba.getchannel("A")
    mask = alpha.point(lambda p: 255 if p > alpha_threshold else 0)
    bbox = mask.getbbox()
    if not bbox:
        return rgba
    return rgba.crop(bbox)


def fit_transparent_square_canvas(image: Image.Image, size: int, extra_px: int = 4) -> Image.Image:
    cropped = trim_transparent_edges(image)
    scale = (size + extra_px) / max(cropped.width, cropped.height)
    new_w = max(1, round(cropped.width * scale))
    new_h = max(1, round(cropped.height * scale))
    resized = cropped.resize((new_w, new_h), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.alpha_composite(resized, ((size - new_w) // 2, (size - new_h) // 2))
    return canvas


def trim_and_fit_long_edge(image: Image.Image, target_edge: int, extra_px: int = 4) -> Image.Image:
    cropped = trim_transparent_edges(image)
    scale = (target_edge + extra_px) / max(cropped.width, cropped.height)
    new_w = max(1, round(cropped.width * scale))
    new_h = max(1, round(cropped.height * scale))
    return cropped.resize((new_w, new_h), Image.Resampling.LANCZOS)


def generate_vip_transparent_image(image: Image.Image, target_edge: int = 1200, extra_px: int = 10) -> Image.Image:
    cropped = trim_transparent_edges(image)
    scale = target_edge / max(cropped.width, cropped.height)
    base_size = (max(1, round(cropped.width * scale)), max(1, round(cropped.height * scale)))
    base = cropped.resize(base_size, Image.Resampling.LANCZOS)

    work = Image.new("RGBA", (target_edge, target_edge), (0, 0, 0, 0))
    work.alpha_composite(base, ((target_edge - base.width) // 2, (target_edge - base.height) // 2))
    cropped_work = trim_transparent_edges(work)
    final_size = _ensure_target_edge(cropped_work.size, target_edge)

    scale_after_crop = (max(cropped_work.width, cropped_work.height) + extra_px) / max(cropped_work.width, cropped_work.height)
    enlarged_size = (
        max(1, round(cropped_work.width * scale_after_crop)),
        max(1, round(cropped_work.height * scale_after_crop)),
    )
    enlarged = cropped_work.resize(enlarged_size, Image.Resampling.LANCZOS)

    final_canvas = Image.new("RGBA", final_size, (0, 0, 0, 0))
    final_canvas.alpha_composite(enlarged, ((final_size[0] - enlarged.width) // 2, (final_size[1] - enlarged.height) // 2))
    return final_canvas


def _ensure_target_edge(size: tuple[int, int], target_edge: int) -> tuple[int, int]:
    width, height = size
    if width >= height:
        return (target_edge, height)
    return (width, target_edge)


def process_square_transparent_image(
    source: Path,
    output: Path,
    size: int,
    max_bytes: int,
    report: dict,
    platform: str,
    usage: str,
) -> Path | None:
    try:
        image = open_image(source).convert("RGBA")
        result = fit_transparent_square_canvas(image, size)
        return save_png_under(result, output, max_bytes, report, source, platform, usage, [f"透明裁边后长边贴合{size}px", "按比例额外放大4px后居中放入方形画布"])
    except Exception as exc:
        add_failure(report, "处理方形透明图失败", 源文件=str(source), 输出文件=str(output), 错误=str(exc))
        return None


def process_adaptive_transparent_image(
    source: Path,
    output: Path,
    target_edge: int,
    max_bytes: int,
    report: dict,
    platform: str,
    usage: str,
) -> Path | None:
    try:
        image = open_image(source).convert("RGBA")
        result = trim_and_fit_long_edge(image, target_edge)
        if target_edge + 4 not in result.size:
            add_risk(report, "透明图自适应处理后没有任一边等于目标尺寸加4px", 文件=str(output), 目标边=target_edge, 实际尺寸=list(result.size))
        return save_png_under(result, output, max_bytes, report, source, platform, usage, [f"透明裁边后长边贴合{target_edge}px", "按比例额外放大4px，不补成方图"])
    except Exception as exc:
        add_failure(report, "处理自适应透明图失败", 源文件=str(source), 输出文件=str(output), 错误=str(exc))
        return None


def process_vip_transparent_image(
    source: Path,
    output: Path,
    target_edge: int,
    max_bytes: int,
    report: dict,
    platform: str,
    usage: str,
) -> Path | None:
    try:
        image = open_image(source).convert("RGBA")
        result = generate_vip_transparent_image(image, target_edge)
        if target_edge not in result.size:
            add_risk(report, "唯品会透明图处理后没有任一边等于目标尺寸", 文件=str(output), 目标边=target_edge, 实际尺寸=list(result.size))
        return save_png_under(
            result,
            output,
            max_bytes,
            report,
            source,
            platform,
            usage,
            [f"提取800透明图主体", f"等比例缩放到{target_edge}x{target_edge}工作图", "按产品透明边裁切", "主体额外放大10px，最终画布保持一边1200"],
        )
    except Exception as exc:
        add_failure(report, "process_vip_transparent_image失败", 源文件=str(source), 输出文件=str(output), 错误=str(exc))
        return None


def alpha_bbox_ratio(path: Path) -> float:
    try:
        image = Image.open(path).convert("RGBA")
        alpha = image.getchannel("A")
        bbox = alpha.point(lambda p: 255 if p > 8 else 0).getbbox()
        if not bbox:
            return 0.0
        box_w = bbox[2] - bbox[0]
        box_h = bbox[3] - bbox[1]
        return (box_w * box_h) / (image.width * image.height)
    except Exception:
        return 0.0
