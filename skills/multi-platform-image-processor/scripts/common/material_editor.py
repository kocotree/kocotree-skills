from __future__ import annotations

import logging
import re
import statistics
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

from .font_assets import FontAsset, require_glyphs
from .utils import ensure_dir

logger = logging.getLogger(__name__)

_WRAP_TOKEN_PATTERN = re.compile(r"\([^()\n]*\)|\d+(?:\.\d+)?%?|\n|.", re.DOTALL)


@dataclass(frozen=True)
class TextStyle:
    """定义面料重绘的版式参数。"""

    font_size: int
    color: tuple[int, int, int]
    line_spacing: int = 6


@dataclass(frozen=True)
class MeasuredMaterialLayout:
    """保存从原图测得的材质文字布局。"""

    font_size: int
    text_right: int
    reference_right: int
    padding_top: int
    line_spacing: int
    source_ink_height: int


def font_role(character: str) -> str:
    """返回单个字符对应的字体角色。"""
    if character == "1":
        return "数字1"
    if character.isdigit() or character == ".":
        return "G8321"
    return "方正兰亭中黑"


def normalize_parentheses(text: str) -> str:
    """将面料文字中的全角括号统一为英文括号。"""
    return text.replace("（", "(").replace("）", ")")


def normalize_material_text(text: str) -> str:
    """规范详情页面料文字的标签层级和括号。

    参数：
        text：产品信息 Excel 中的中文面料原文。
    返回值：
        可用于详情页重绘的面料文字。
    """
    normalized = normalize_parentheses(text.strip())
    outer_label = re.match(r"^面料\s*[:：]\s*", normalized)
    if outer_label:
        remainder = normalized[outer_label.end():]
        if re.match(r"^[^:：\n]{1,12}\s*[:：]", remainder):
            normalized = remainder
    return normalized


def split_font_runs(text: str) -> list[tuple[str, str]]:
    """将文本按连续字体角色拆分。"""
    runs: list[tuple[str, str]] = []
    for character in text:
        role = font_role(character)
        if runs and runs[-1][0] == role:
            runs[-1] = (role, runs[-1][1] + character)
        else:
            runs.append((role, character))
    return runs


def _load_render_fonts(
    text: str,
    fonts: dict[str, FontAsset],
    font_size: int,
) -> dict[str, ImageFont.FreeTypeFont]:
    """加载一段面料文本需要的字体角色。"""
    loaded: dict[str, ImageFont.FreeTypeFont] = {}
    for role, run in split_font_runs(text):
        asset = fonts[role]
        require_glyphs(asset, run)
        loaded.setdefault(role, ImageFont.truetype(str(asset.path), font_size))
    return loaded


def _mixed_text_width(text: str, loaded: dict[str, ImageFont.FreeTypeFont]) -> float:
    """计算混合字体文本的总宽度。"""
    return sum(loaded[role].getlength(run) for role, run in split_font_runs(text))


def mixed_line_height(
    text: str,
    fonts: dict[str, FontAsset],
    font_size: int,
    line_spacing: int = 0,
) -> int:
    """计算混合字体一行文字占用的高度。"""
    loaded = _load_render_fonts(text, fonts, font_size)
    return max(sum(font.getmetrics()) for font in loaded.values()) + line_spacing


def _content_mask(
    image: Image.Image,
    region: tuple[int, int, int, int],
    background: tuple[int, int, int],
    threshold: int = 20,
) -> Image.Image:
    """提取纯色背景区域中的非背景像素。"""
    crop = image.convert("RGB").crop(region)
    difference = ImageChops.difference(
        crop,
        Image.new("RGB", crop.size, background),
    )
    channels = [
        channel.point(lambda value: 255 if value > threshold else 0)
        for channel in difference.split()
    ]
    return ImageChops.lighter(ImageChops.lighter(channels[0], channels[1]), channels[2])


def _text_rows(mask: Image.Image, maximum_gap: int = 2) -> list[tuple[int, int]]:
    """根据水平投影返回文字行的纵向范围。"""
    rows: list[tuple[int, int]] = []
    start: int | None = None
    last: int | None = None
    for y in range(mask.height):
        if mask.crop((0, y, mask.width, y + 1)).getbbox():
            if start is None:
                start = y
            last = y
        elif start is not None and last is not None and y - last > maximum_gap:
            rows.append((start, last + 1))
            start = None
            last = None
    if start is not None and last is not None:
        rows.append((start, last + 1))
    return [row for row in rows if row[1] - row[0] >= 4]


def _rendered_ink_metrics(
    text: str,
    fonts: dict[str, FontAsset],
    font_size: int,
) -> tuple[int, int, int, int]:
    """返回混合字体单行的墨迹宽、高、顶部和右侧偏移。"""
    canvas = Image.new("RGB", (3000, 300), (255, 255, 255))
    draw_mixed_text(
        canvas,
        (20, 20),
        text,
        fonts,
        TextStyle(font_size, (0, 0, 0), 0),
    )
    mask = ImageChops.difference(
        canvas,
        Image.new("RGB", canvas.size, (255, 255, 255)),
    ).convert("L")
    box = mask.getbbox()
    if box is None:
        raise RuntimeError("无法测量面料字体墨迹")
    return box[2] - box[0], box[3] - box[1], box[1] - 20, box[2] - 20


def measure_material_layout(
    source: Path,
    region: tuple[int, int, int, int],
    reference_regions: list[tuple[int, int, int, int]],
    text: str,
    fonts: dict[str, FontAsset],
    background: tuple[int, int, int],
    horizontal_padding: int = 0,
) -> MeasuredMaterialLayout:
    """从原图测量材质字号、行距和上下字段共同右边界。

    参数：
        source：包含原材质文字的详情图。
        region：允许重绘的材质文字区域。
        reference_regions：名称、货号、颜色或尺码等右侧文字区域。
        text：准备写入的 Excel 中文面料原文。
        fonts：已校验字体角色映射。
        background：信息卡纯色背景。
        horizontal_padding：材质区域左侧保留距离。
    返回值：
        Pillow 实测得到的渲染布局。
    """
    with Image.open(source) as opened:
        image = opened.convert("RGB")
    material_mask = _content_mask(image, region, background)
    source_rows = _text_rows(material_mask)
    if not source_rows:
        raise RuntimeError("原材质区域没有检测到文字行")
    source_height = round(statistics.median(end - start for start, end in source_rows))
    reference_edges: list[int] = []
    for reference in reference_regions:
        box = _content_mask(image, reference, background).getbbox()
        if box is not None:
            reference_edges.append(reference[0] + box[2])
    if len(reference_edges) < 2:
        raise RuntimeError("上下字段参考区域不足，无法测量共同右边界")
    reference_right = int(statistics.median(reference_edges) + 0.5)
    normalized = normalize_material_text(text)
    logical_lines = [line for line in normalized.splitlines() if line]
    if not logical_lines:
        raise RuntimeError("面料文字不能为空")
    maximum_width = reference_right - (region[0] + horizontal_padding)
    candidates: list[tuple[int, int]] = []
    for candidate in range(8, 81):
        metrics = [_rendered_ink_metrics(line, fonts, candidate) for line in logical_lines]
        if max(width for width, _, _, _ in metrics) <= maximum_width:
            rendered_height = statistics.median(height for _, height, _, _ in metrics)
            candidates.append((abs(round(rendered_height) - source_height), candidate))
    if not candidates:
        raise RuntimeError("面料文字无法适配原版式宽度")
    font_size = min(candidates)[1]
    line_metrics = [_rendered_ink_metrics(line, fonts, font_size) for line in logical_lines]
    first_ink_offset = line_metrics[0][2]
    padding_top = max(0, source_rows[0][0] - first_ink_offset)
    natural_step = mixed_line_height(normalized, fonts, font_size, 0)
    if len(source_rows) >= 2 and len(line_metrics) >= 2:
        source_step = round(statistics.median(
            source_rows[index + 1][0] - source_rows[index][0]
            for index in range(len(source_rows) - 1)
        ))
        offset_change = line_metrics[1][2] - line_metrics[0][2]
        line_spacing = source_step - offset_change - natural_step
    else:
        line_spacing = 0
    text_right = reference_right
    logger.info(
        "面料布局测量完成 source=%r font_size=%d reference_right=%d "
        "text_right=%d source_ink_height=%d line_spacing=%d",
        str(source),
        font_size,
        reference_right,
        text_right,
        source_height,
        line_spacing,
    )
    return MeasuredMaterialLayout(
        font_size,
        text_right,
        reference_right,
        padding_top,
        line_spacing,
        source_height,
    )


def verify_measured_material_layout(
    image_path: Path,
    region: tuple[int, int, int, int],
    background: tuple[int, int, int],
    expected_right: int,
    expected_ink_height: int,
    tolerance: int = 2,
) -> None:
    """复测材质文字的右边界和字高。"""
    with Image.open(image_path) as opened:
        mask = _content_mask(opened, region, background)
    box = mask.getbbox()
    rows = _text_rows(mask)
    if box is None or not rows:
        raise RuntimeError("重绘后没有检测到材质文字")
    actual_height = round(statistics.median(end - start for start, end in rows))
    for start, end in rows:
        line_box = mask.crop((0, start, mask.width, end)).getbbox()
        if line_box is None:
            continue
        actual_right = region[0] + line_box[2]
        if abs(actual_right - expected_right) > tolerance:
            raise RuntimeError(
                f"材质右边界复测失败：实际 {actual_right}，目标 {expected_right}"
            )
    if abs(actual_height - expected_ink_height) > tolerance:
        raise RuntimeError(
            f"材质字高复测失败：实际 {actual_height}，目标 {expected_ink_height}"
        )


def wrap_mixed_text(
    text: str,
    fonts: dict[str, FontAsset],
    font_size: int,
    maximum_width: int,
) -> list[str]:
    """按目标区域宽度换行并保持括号、数字和百分号整体。"""
    if not text:
        raise RuntimeError("面料文字不能为空")
    loaded = _load_render_fonts(text, fonts, font_size)
    lines: list[str] = []
    current = ""
    for token in _WRAP_TOKEN_PATTERN.findall(text):
        if token == "\n":
            lines.append(current)
            current = ""
            continue
        if _mixed_text_width(token, loaded) > maximum_width:
            raise RuntimeError(f"面料文字整体超出指定宽度：{token}")
        candidate = current + token
        if current and _mixed_text_width(candidate, loaded) > maximum_width:
            lines.append(current)
            current = token
        else:
            current = candidate
    if current or not lines:
        lines.append(current)
    return lines


def draw_mixed_text(
    image: Image.Image,
    position: tuple[int, int],
    text: str,
    fonts: dict[str, FontAsset],
    style: TextStyle,
) -> tuple[int, int, int, int]:
    """使用三个字体角色在统一基线上绘制面料文字。

    参数：
        image：需要绘制的 RGB 图片。
        position：文字左上参考点。
        text：Excel 中文面料原文。
        fonts：已校验字体角色映射。
        style：字号、颜色和行距。
    返回值：
        实际绘制区域的边界框。
    """
    runs = split_font_runs(text)
    if not runs:
        raise RuntimeError("面料文字不能为空")
    loaded = _load_render_fonts(text, fonts, style.font_size)
    baseline = position[1] + max(font.getmetrics()[0] for font in loaded.values())
    draw = ImageDraw.Draw(image)
    cursor = position[0]
    top = position[1]
    bottom = baseline
    for role, run in runs:
        font = loaded[role]
        draw.text((cursor, baseline), run, font=font, fill=style.color, anchor="ls")
        box = draw.textbbox((cursor, baseline), run, font=font, anchor="ls")
        cursor = box[2]
        top = min(top, box[1])
        bottom = max(bottom, box[3])
    return position[0], top, cursor, bottom


def replace_material_text(
    source: Path,
    output: Path,
    region: tuple[int, int, int, int],
    text: str,
    fonts: dict[str, FontAsset],
    style: TextStyle,
    background: tuple[int, int, int] | Image.Image,
    padding: tuple[int, int] = (0, 0),
    right_edge: int | None = None,
) -> Path:
    """在指定区域清理并重绘中文面料。

    参数：
        source：源详情图。
        output：修改图路径。
        region：允许修改的文字区域。
        text：Excel 中文面料原文。
        fonts：已校验的字体角色映射。
        style：版式参数。
        background：目标区域的纯色或干净背景块。
        padding：文字相对区域左上角的内边距。
        right_edge：文字与上下字段共用的绝对横坐标右边界。
    返回值：
        修改后的图片路径。
    """
    with Image.open(source) as opened:
        image = opened.convert("RGB")
    left, top, right, bottom = region
    if not (0 <= left < right <= image.width and 0 <= top < bottom <= image.height):
        raise RuntimeError("面料重绘区域超出源图")
    if isinstance(background, Image.Image):
        patch = background.convert("RGB")
        if patch.size != (right - left, bottom - top):
            raise RuntimeError("干净背景块尺寸与面料区域不一致")
        image.paste(patch, (left, top))
    else:
        ImageDraw.Draw(image).rectangle(region, fill=background)
    text_left = left + padding[0]
    text_right = right_edge if right_edge is not None else right - padding[0]
    text_top = top + padding[1]
    if not text_left < text_right <= right:
        raise RuntimeError("面料文字右边界超出指定区域")
    maximum_width = text_right - text_left
    normalized_text = normalize_material_text(text)
    lines = wrap_mixed_text(normalized_text, fonts, style.font_size, maximum_width)
    line_height = mixed_line_height(
        normalized_text,
        fonts,
        style.font_size,
        style.line_spacing,
    )
    for line_index, line in enumerate(lines):
        if not line:
            continue
        ink_right_offset = _rendered_ink_metrics(line, fonts, style.font_size)[3]
        line_left = text_right - ink_right_offset
        if line_left < text_left:
            raise RuntimeError("面料文字超出指定区域")
        drawn = draw_mixed_text(
            image,
            (line_left, text_top + line_index * line_height),
            line,
            fonts,
            style,
        )
        if drawn[2] > right or drawn[3] > bottom:
            raise RuntimeError("面料文字超出指定区域")
    ensure_dir(output.parent)
    image.save(output, quality=95)
    logger.info("面料文字重绘完成 source=%r output=%r region=%r", str(source), str(output), region)
    return output


def verify_non_target_unchanged(
    before: Path,
    after: Path,
    regions: list[tuple[int, int, int, int]],
    difference_threshold: int = 0,
    maximum_changed_ratio: float = 0.0,
) -> bool:
    """检查允许修改区域以外的像素是否完全一致。

    参数：
        before：修改前图片。
        after：修改后图片。
        regions：允许发生变化的矩形列表。
        difference_threshold：忽略的单像素灰度差异上限。
        maximum_changed_ratio：允许的非目标区域变化比例。
    返回值：
        非目标区域完全一致时返回 True。
    """
    with Image.open(before) as opened:
        source = opened.convert("RGB")
    with Image.open(after) as opened:
        target = opened.convert("RGB")
    if source.size != target.size:
        return False
    difference = ImageChops.difference(source, target)
    mask = Image.new("L", source.size, 255)
    draw = ImageDraw.Draw(mask)
    for region in regions:
        draw.rectangle(region, fill=0)
    outside = ImageChops.multiply(difference.convert("L"), mask)
    changed = outside.point(lambda value: 255 if value > difference_threshold else 0)
    histogram = changed.histogram()
    changed_pixels = sum(histogram[1:])
    allowed_pixels = sum(mask.histogram()[1:])
    ratio = changed_pixels / allowed_pixels if allowed_pixels else 0.0
    return ratio <= maximum_changed_ratio
