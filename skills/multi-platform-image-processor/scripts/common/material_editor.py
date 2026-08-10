from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

from .font_assets import FontAsset, require_glyphs
from .utils import ensure_dir


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TextStyle:
    """定义面料重绘的版式参数。"""

    font_size: int
    color: tuple[int, int, int]
    line_spacing: int = 6


def font_role(character: str) -> str:
    """返回单个字符对应的字体角色。"""
    if character == "1":
        return "数字1"
    if character.isdigit() or character == ".":
        return "G8321"
    return "方正兰亭中黑"


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


def wrap_mixed_text(
    text: str,
    fonts: dict[str, FontAsset],
    font_size: int,
    maximum_width: int,
) -> list[str]:
    """按目标区域宽度为混合字体文本换行。"""
    if not text:
        raise RuntimeError("面料文字不能为空")
    loaded = _load_render_fonts(text, fonts, font_size)
    lines: list[str] = []
    current = ""
    for character in text:
        if character == "\n":
            lines.append(current)
            current = ""
            continue
        candidate = current + character
        if current and _mixed_text_width(candidate, loaded) > maximum_width:
            lines.append(current)
            current = character
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
    text_top = top + padding[1]
    maximum_width = right - text_left
    lines = wrap_mixed_text(text, fonts, style.font_size, maximum_width)
    loaded = _load_render_fonts(text, fonts, style.font_size)
    line_height = max(sum(font.getmetrics()) for font in loaded.values()) + style.line_spacing
    for line_index, line in enumerate(lines):
        if not line:
            continue
        drawn = draw_mixed_text(
            image,
            (text_left, text_top + line_index * line_height),
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
) -> bool:
    """检查允许修改区域以外的像素是否完全一致。

    参数：
        before：修改前图片。
        after：修改后图片。
        regions：允许发生变化的矩形列表。
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
    return outside.getbbox() is None
