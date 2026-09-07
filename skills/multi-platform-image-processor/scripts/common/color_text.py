from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from statistics import median

from PIL import Image, ImageChops, ImageFilter

from .settings import config_root, load_json_config

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def color_name_rules() -> dict[str, str]:
    """读取蜂享家＋爱库存的颜色名称替换规则。"""
    return load_json_config(config_root() / "color_name_rules.json")


def rename_color_file(path: Path) -> Path:
    """只替换颜色文件名，保留业务分支目录。"""
    name = path.name
    for original, replacement in color_name_rules().items():
        name = name.replace(original, replacement)
    return path.with_name(name)


def _background(image: Image.Image, box: tuple[int, int, int, int]) -> Image.Image:
    """从文字上下的空白行插值恢复纯色或纵向渐变背景。"""
    left, top, right, bottom = box
    if not (0 <= left < right <= image.width and 0 < top < bottom < image.height):
        raise ValueError("颜色文字区域需要位于图内并留有上下空白采样行")
    patch = Image.new("RGB", (right - left, bottom - top))
    pixels = []
    for y in range(patch.height):
        ratio = (y + 1) / (patch.height + 1)
        for x in range(left, right):
            above, below = image.getpixel((x, top - 1)), image.getpixel((x, bottom))
            pixels.append(tuple(round(a + (b - a) * ratio) for a, b in zip(above, below)))
    patch.putdata(pixels)
    return patch


def _glyph(image: Image.Image, box: tuple[int, int, int, int]) -> tuple[Image.Image, tuple[int, int, int]]:
    """从字形与背景的对比中提取透明度和原文字颜色。"""
    crop = image.crop(box)
    background = _background(image, box)
    crop_pixels, background_pixels = crop.load(), background.load()
    pairs = [(crop_pixels[x, y], background_pixels[x, y])
             for y in range(crop.height) for x in range(crop.width)]
    contrasts = [max(abs(a - b) for a, b in zip(pixel, bg)) for pixel, bg in pairs]
    maximum = max(contrasts)
    if maximum < 15:
        raise ValueError("颜色文字参考区域没有可辨识的字形")
    solid = [pixel for (pixel, _), contrast in zip(pairs, contrasts) if contrast >= maximum * .85]
    color = tuple(round(median(pixel[c] for pixel in solid)) for c in range(3))
    alpha = []
    for pixel, bg in pairs:
        vector = tuple(f - b for f, b in zip(color, bg))
        denominator = sum(v * v for v in vector)
        value = sum((p - b) * v for p, b, v in zip(pixel, bg, vector)) / max(denominator, 1)
        alpha.append(max(0, min(255, round(value * 255))))
    mask = Image.new("L", crop.size)
    mask.putdata(alpha)
    return mask, color


def _clean_glyph_mask(mask: Image.Image) -> Image.Image:
    """提取参考字的主要笔画，排除独立小碎片并保留抗锯齿边缘。

    参数：
        mask：参考字形的灰度透明度蒙版。
    返回值：
        保持原尺寸和笔画位置的清理后蒙版。
    """
    pixels = mask.load()
    points = {(x, y) for y in range(mask.height) for x in range(mask.width)
              if pixels[x, y] >= 45}
    components = []
    while points:
        seed = points.pop()
        stack, component = [seed], [seed]
        while stack:
            x, y = stack.pop()
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    neighbor = (x + dx, y + dy)
                    if neighbor in points:
                        points.remove(neighbor)
                        stack.append(neighbor)
                        component.append(neighbor)
        components.append(component)
    if not components:
        return mask.copy()
    largest = max(map(len, components))
    retained = [part for part in components if len(part) >= largest * .1]
    support = Image.new("L", mask.size)
    for part in retained:
        for point in part:
            support.putpixel(point, 255)
    # 扩展一像素仅用于保留原蒙版中的抗锯齿透明度，笔画本身不加粗。
    support = support.filter(ImageFilter.MaxFilter(3))
    logger.info("参考字形提取 components=%s retained=%s",
                sorted(map(len, components)), sorted(map(len, retained)))
    return ImageChops.multiply(mask, support)


def replace_color_glyphs(source: Path, output: Path, items: list[dict], source_root: Path) -> Path:
    """用原图同字体、同字号的参考字形替换颜色中的目标字。

    参数：
        source：源图或已完成材质修改的无损图。
        output：只供目标平台使用的 PNG 临时图。
        items：Agent 确认的原字区域、同尺寸参考字区域及原文。
        source_root：参考图片相对路径所属的原始素材目录。
    返回值：
        无损修改图路径；原字区域以外的像素保持不变。
    """
    with Image.open(source) as opened:
        original = opened.convert("RGB")
    image = original.copy()
    for item in items:
        text = item["原文"]
        if not any(value in text for value in color_name_rules()):
            raise ValueError("颜色原文未命中平台替换规则")
        box = tuple(item["原字区域"])
        reference_box = tuple(item["参考字区域"])
        reference_path = (source_root / item["参考图片"]).resolve()
        reference_path.relative_to(source_root.resolve())
        with Image.open(reference_path) as opened:
            reference = opened.convert("RGB")
        mask, _ = _glyph(reference, reference_box)
        mask = _clean_glyph_mask(mask)
        background = _background(original, box)
        if mask.size != background.size:
            raise ValueError("参考字与目标字应使用同字号、同尺寸字框")
        _, color = _glyph(original, box)
        patch = Image.new("RGB", mask.size, color)
        background.paste(patch, (0, 0), mask)
        image.paste(background, box[:2])
        logger.info("颜色文字替换 source=%r text=%s box=%s reference=%r",
                    str(source), text, box, str(reference_path))
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, "PNG")
    return output


def prepare_color_overrides(source_root: Path, items: list[dict], staging: Path,
                            base_overrides: dict[Path, Path] | None = None) -> dict[Path, Path]:
    """按颜色视觉计划生成目标平台专用的源图覆盖映射。

    参数：
        source_root：只读产品素材目录。
        items：按源图坐标记录的颜色文字定位项。
        staging：临时 PNG 保存目录。
        base_overrides：已经完成的面料修正映射。
    返回值：
        保留已有面料修正的原图到颜色修正版路径映射。
    """
    overrides = dict(base_overrides or {})
    grouped: dict[Path, list[dict]] = {}
    for item in items:
        path = (source_root / item["图片"]).resolve()
        path.relative_to(source_root.resolve())
        grouped.setdefault(path, []).append(item)
    for path, edits in grouped.items():
        relative = path.relative_to(source_root.resolve())
        target = staging / relative.parent / (relative.name + ".png")
        overrides[path] = replace_color_glyphs(overrides.get(path, path), target, edits, source_root)
    return overrides
