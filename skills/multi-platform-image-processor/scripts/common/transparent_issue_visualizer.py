from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from .utils import ensure_dir, unique_path


def render_transparent_issue(
    image_path: Path,
    rgba: Image.Image,
    alpha: Image.Image,
    debris: list[dict[str, Any]],
    output_dir: Path,
) -> Path:
    """生成单张透明图脏点诊断图。

    功能说明：在棋盘背景上无覆盖展示原透明图，并在下方使用空心定位框和
    独立透明度证据图展示主体外残留，避免诊断标记遮挡原图内容。

    参数：
        image_path：原透明图路径，用于标题和输出命名。
        rgba：原透明图的 RGBA 图像。
        alpha：原透明图的透明通道。
        debris：主体外独立连通区域信息。
        output_dir：诊断图片输出目录。
    返回值：
        生成的 PNG 诊断图路径。
    """
    ensure_dir(output_dir)
    width, height = rgba.size
    header_height = max(104, round(height * 0.13))
    zoom_height = max(240, round(height * 0.32))
    footer_height = max(88, round(height * 0.11))
    panel = Image.new("RGB", (width, header_height + height + footer_height + zoom_height), "white")
    draw = ImageDraw.Draw(panel)
    title_font = _load_font(max(22, round(width * 0.035)), bold=True)
    text_font = _load_font(max(16, round(width * 0.024)))
    debris_pixels = []
    boxes = []
    for item in debris:
        pixels = _collect_component_pixels(alpha, item["起点"])
        debris_pixels.extend(pixels)
        boxes.append(tuple(item["边界"]))

    total_pixels = sum(item["像素数"] for item in debris)
    draw.text((16, 10), f"{image_path.name} 透明图脏点诊断", font=title_font, fill=(0, 0, 0))
    draw.text(
        (16, 48),
        f"主体外独立区域：{len(debris)} 个；残留像素：{total_pixels} 个。上方原图无任何覆盖。",
        font=text_font,
        fill=(20, 90, 120),
    )
    draw.text((16, 76), "下方左侧为空心框定位，右侧为透明度证据增强显示。", font=text_font, fill=(20, 90, 120))

    original = _checkerboard(rgba.size)
    original.paste(rgba, (0, 0), rgba)
    panel.paste(original, (0, header_height))

    merged_boxes = _merge_boxes(boxes, gap=max(18, round(width * 0.035)))
    zoom_top = header_height + height
    draw.text((16, zoom_top + 8), "问题区域证据", font=title_font, fill=(0, 80, 110))
    draw.text((16, zoom_top + 44), "空心框与编号位于残留外围；青色形状是增强后的残留像素。", font=text_font, fill=(0, 80, 110))
    crop_box = _debris_crop_box(boxes, width, height)
    half_width = width // 2
    left_panel, left_ratio, left_offset = _fit_contain_with_mapping(
        original.crop(crop_box),
        (half_width, zoom_height),
        background=(245, 245, 245),
    )
    evidence = _debris_evidence(rgba.size, debris_pixels).crop(crop_box)
    right_panel, right_ratio, right_offset = _fit_contain_with_mapping(
        evidence,
        (width - half_width, zoom_height),
        background=(18, 23, 27),
    )
    _draw_locator_boxes(left_panel, merged_boxes, crop_box, left_ratio, left_offset, text_font)
    _draw_locator_boxes(right_panel, merged_boxes, crop_box, right_ratio, right_offset, text_font)
    panel.paste(left_panel, (0, zoom_top + footer_height))
    panel.paste(right_panel, (half_width, zoom_top + footer_height))
    draw.line(
        (half_width, zoom_top + footer_height, half_width, zoom_top + footer_height + zoom_height),
        fill=(120, 120, 120),
        width=2,
    )

    output_path = unique_path(output_dir / f"{image_path.stem}-透明图脏点诊断.png")
    panel.save(output_path, format="PNG", optimize=True)
    return output_path


def render_transparent_overview(diagnostic_paths: list[Path], output_dir: Path) -> Path | None:
    """将多张透明图诊断图合成为横向汇总图。

    参数：
        diagnostic_paths：单图诊断文件路径列表。
        output_dir：汇总图输出目录。
    返回值：
        有诊断图时返回汇总 PNG 路径，否则返回 None。
    """
    if not diagnostic_paths:
        return None
    panels = []
    for path in diagnostic_paths:
        with Image.open(path) as image:
            panels.append(image.convert("RGB"))
    target_width = min(800, max(panel.width for panel in panels))
    resized = []
    for panel in panels:
        ratio = target_width / panel.width
        resized.append(panel.resize((target_width, max(1, round(panel.height * ratio))), Image.Resampling.LANCZOS))
    max_height = max(panel.height for panel in resized)
    canvas = Image.new("RGB", (target_width * len(resized), max_height), (238, 238, 238))
    for index, panel in enumerate(resized):
        canvas.paste(panel, (index * target_width, 0))
    output_path = unique_path(ensure_dir(output_dir) / "透明图脏点诊断汇总.png")
    canvas.save(output_path, format="PNG", optimize=True)
    return output_path


def _collect_component_pixels(alpha: Image.Image, start: list[int]) -> list[tuple[int, int]]:
    width, height = alpha.size
    values = alpha.tobytes()
    start_index = start[1] * width + start[0]
    seen = {start_index}
    queue = deque([start_index])
    pixels = []
    while queue:
        current = queue.popleft()
        x = current % width
        y = current // width
        pixels.append((x, y))
        for neighbor_y in range(max(0, y - 1), min(height, y + 2)):
            base = neighbor_y * width
            for neighbor_x in range(max(0, x - 1), min(width, x + 2)):
                neighbor = base + neighbor_x
                if values[neighbor] > 0 and neighbor not in seen:
                    seen.add(neighbor)
                    queue.append(neighbor)
    return pixels


def _checkerboard(size: tuple[int, int], tile: int = 20) -> Image.Image:
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    for y in range(0, size[1], tile):
        for x in range(0, size[0], tile):
            if (x // tile + y // tile) % 2:
                draw.rectangle((x, y, x + tile - 1, y + tile - 1), fill=(214, 214, 214))
    return image


def _merge_boxes(boxes: list[tuple[int, int, int, int]], gap: int) -> list[tuple[int, int, int, int]]:
    merged: list[tuple[int, int, int, int]] = []
    for box in boxes:
        left, top, right, bottom = box
        changed = True
        while changed:
            changed = False
            remaining = []
            for other_left, other_top, other_right, other_bottom in merged:
                separated = (
                    right + gap < other_left
                    or other_right + gap < left
                    or bottom + gap < other_top
                    or other_bottom + gap < top
                )
                if separated:
                    remaining.append((other_left, other_top, other_right, other_bottom))
                    continue
                left = min(left, other_left)
                top = min(top, other_top)
                right = max(right, other_right)
                bottom = max(bottom, other_bottom)
                changed = True
            merged = remaining
        merged.append((left, top, right, bottom))
    return merged


def _debris_crop_box(
    boxes: list[tuple[int, int, int, int]],
    width: int,
    height: int,
) -> tuple[int, int, int, int]:
    left = min(box[0] for box in boxes)
    top = min(box[1] for box in boxes)
    right = max(box[2] for box in boxes)
    bottom = max(box[3] for box in boxes)
    padding_x = max(30, round((right - left) * 0.16))
    padding_y = max(24, round((bottom - top) * 0.35))
    return _expand_box((left, top, right, bottom), width, height, max(padding_x, padding_y))


def _expand_box(
    box: tuple[int, int, int, int],
    width: int,
    height: int,
    padding: int,
) -> tuple[int, int, int, int]:
    left, top, right, bottom = box
    return max(0, left - padding), max(0, top - padding), min(width, right + padding), min(height, bottom + padding)


def _fit_contain_with_mapping(
    image: Image.Image,
    size: tuple[int, int],
    background: tuple[int, int, int],
) -> tuple[Image.Image, float, tuple[int, int]]:
    """等比放入画布，并返回原图坐标映射所需的缩放率和偏移量。"""
    ratio = min(size[0] / image.width, size[1] / image.height)
    resized = image.resize((max(1, round(image.width * ratio)), max(1, round(image.height * ratio))), Image.Resampling.NEAREST)
    canvas = Image.new("RGB", size, background)
    offset = ((size[0] - resized.width) // 2, (size[1] - resized.height) // 2)
    canvas.paste(resized, offset)
    return canvas, ratio, offset


def _debris_evidence(size: tuple[int, int], pixels: list[tuple[int, int]]) -> Image.Image:
    """生成独立的残留像素增强证据图，不在原图上叠加颜色。"""
    evidence = Image.new("RGB", size, (18, 23, 27))
    values = evidence.load()
    for x, y in pixels:
        values[x, y] = (0, 220, 255)
    return evidence


def _draw_locator_boxes(
    image: Image.Image,
    boxes: list[tuple[int, int, int, int]],
    crop_box: tuple[int, int, int, int],
    ratio: float,
    offset: tuple[int, int],
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
) -> None:
    """在残留外围绘制空心框和编号，框线不覆盖残留像素。"""
    draw = ImageDraw.Draw(image)
    crop_left, crop_top, _, _ = crop_box
    padding = max(5, round(6 * ratio))
    line_width = max(2, round(image.width / 220))
    for index, box in enumerate(boxes, 1):
        left = round((box[0] - crop_left) * ratio) + offset[0] - padding
        top = round((box[1] - crop_top) * ratio) + offset[1] - padding
        right = round((box[2] - crop_left) * ratio) + offset[0] + padding
        bottom = round((box[3] - crop_top) * ratio) + offset[1] + padding
        left = max(0, left)
        top = max(0, top)
        right = min(image.width - 1, right)
        bottom = min(image.height - 1, bottom)
        draw.rectangle((left, top, right, bottom), outline=(255, 180, 0), width=line_width)
        label_size = max(22, round(24 * min(2.0, ratio)))
        label_left = min(max(0, left), max(0, image.width - label_size))
        label_top = max(0, top - label_size - 3)
        draw.rounded_rectangle(
            (label_left, label_top, label_left + label_size, label_top + label_size),
            radius=max(3, label_size // 5),
            fill=(255, 180, 0),
        )
        draw.text(
            (label_left + label_size // 2, label_top + label_size // 2),
            str(index),
            fill=(20, 20, 20),
            anchor="mm",
            font=font,
        )


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        Path("C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc"),
        Path("/System/Library/Fonts/PingFang.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    ]
    for candidate in candidates:
        if candidate.exists():
            try:
                return ImageFont.truetype(str(candidate), size)
            except OSError:
                continue
    return ImageFont.load_default()
