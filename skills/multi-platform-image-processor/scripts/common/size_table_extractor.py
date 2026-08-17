from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .certificate_composer import save_business_jpeg, trim_white
from .font_assets import FontAsset, load_font_assets, require_glyphs

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CropBox:
    """定义尺码表内容的完整裁切矩形。"""

    left: int
    top: int
    right: int
    bottom: int

    def as_tuple(self) -> tuple[int, int, int, int]:
        """返回 Pillow 使用的裁切坐标。"""
        return self.left, self.top, self.right, self.bottom


def extract_size_table(source: Path, output: Path, content_box: CropBox) -> Path:
    """按视觉确认坐标提取完整实际尺码表。

    参数：
        source：包含实际尺码表的详情图。
        output：裁切后的图片路径。
        content_box：排除标题和外层边框后的完整表格坐标。
    返回值：
        尺码表图片路径。
    """
    with Image.open(source) as image:
        if not (
            0 <= content_box.left < content_box.right <= image.width
            and 0 <= content_box.top < content_box.bottom <= image.height
        ):
            raise RuntimeError(f"尺码表裁切范围超出源图：{source}")
        table = image.convert("RGB").crop(content_box.as_tuple())
    if table.width < 100 or table.height < 60:
        raise RuntimeError("尺码表裁切区域过小，无法保证清晰完整")
    output.parent.mkdir(parents=True, exist_ok=True)
    table.save(output, "PNG", optimize=True)
    logger.info("尺码表提取完成 source=%r output=%r box=%r", str(source), str(output), content_box.as_tuple())
    return output


_CANVAS_SIZE = 800
_CONTENT_WIDTH = 740
_CONTENT_HEIGHT = 760
_CERTIFICATE_WIDTH_RATIO = 0.8
_CERTIFICATE_GAP = 22
_UNIT_GAP = 8
_UNIT_FONT_SIZE = 24


def _resize_to_width(image: Image.Image, width: int) -> Image.Image:
    """将图片等比例缩放到指定宽度。"""
    height = max(1, round(image.height * width / image.width))
    return image.resize((width, height), Image.Resampling.LANCZOS)


def _unit_role(character: str) -> str:
    """返回尺码单位字符使用的字体角色。"""
    if character == "1":
        return "数字1"
    if character.isascii() and character.isalnum():
        return "G8321"
    return "方正兰亭中黑"


def _render_size_unit(
    unit_value: str,
    fonts: dict[str, FontAsset],
) -> Image.Image:
    """按固定字号绘制来源尺码单位。

    参数：
        unit_value：详情页实际使用的尺码单位文字。
        fonts：业务字体角色映射。
    返回值：
        白底紧边界单位图片。
    """
    normalized = unit_value.strip().lstrip("/").strip()
    if not normalized or any(character.isspace() for character in normalized):
        raise RuntimeError("尺码单位文字为空或包含空白")
    text = f"/{normalized}"
    runs: list[tuple[str, str]] = []
    for character in text:
        role = _unit_role(character)
        if runs and runs[-1][0] == role:
            runs[-1] = (role, runs[-1][1] + character)
        else:
            runs.append((role, character))
    loaded: dict[str, ImageFont.FreeTypeFont] = {}
    for role, run in runs:
        require_glyphs(fonts[role], run)
        loaded.setdefault(role, ImageFont.truetype(str(fonts[role].path), _UNIT_FONT_SIZE))
    ascent = max(font.getmetrics()[0] for font in loaded.values())
    descent = max(font.getmetrics()[1] for font in loaded.values())
    width = max(1, math.ceil(sum(loaded[role].getlength(run) for role, run in runs)))
    image = Image.new("RGB", (width + 4, ascent + descent + 4), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    x = 2.0
    baseline = 2 + ascent
    for role, run in runs:
        draw.text((x, baseline), run, font=loaded[role], fill=(35, 35, 35), anchor="ls")
        x += loaded[role].getlength(run)
    return trim_white(image)


def compose_size_image(
    certificate_image: Path,
    size_table: Path,
    size_unit: str,
    output: Path,
    fonts: dict[str, FontAsset] | None = None,
) -> Path:
    """生成 800×800 合格证与尺码表组合图。

    参数：
        certificate_image：不含面料的 BarTender 导出图。
        size_table：完整实际尺码表裁切图。
        size_unit：详情页实际使用的尺码单位文字。
        output：目标 JPG 路径。
        fonts：可选的业务字体角色映射。
    返回值：
        生成的尺码图路径。
    """
    with Image.open(certificate_image) as opened:
        original_certificate = trim_white(opened)
    with Image.open(size_table) as opened:
        original_table = trim_white(opened)
    unit = _render_size_unit(size_unit, fonts or load_font_assets())
    fixed_height = _CERTIFICATE_GAP + unit.height + _UNIT_GAP
    table_ratio = original_table.width / original_table.height
    certificate_ratio = original_certificate.width / original_certificate.height
    width_by_height = math.floor(
        (_CONTENT_HEIGHT - fixed_height)
        / (1 / table_ratio + _CERTIFICATE_WIDTH_RATIO / certificate_ratio)
    )
    table_width = min(_CONTENT_WIDTH, original_table.width, width_by_height)
    if table_width < 100:
        raise RuntimeError("合格证与尺码表无法在 800×800 画布内清晰排版")
    table = _resize_to_width(original_table, table_width)
    certificate = _resize_to_width(
        original_certificate,
        round(table.width * _CERTIFICATE_WIDTH_RATIO),
    )
    canvas = Image.new("RGB", (_CANVAS_SIZE, _CANVAS_SIZE), (255, 255, 255))
    total_height = certificate.height + fixed_height + table.height
    top = (_CANVAS_SIZE - total_height) // 2
    canvas.paste(certificate, ((_CANVAS_SIZE - certificate.width) // 2, top))
    table_left = (_CANVAS_SIZE - table.width) // 2
    unit_top = top + certificate.height + _CERTIFICATE_GAP
    canvas.paste(unit, (table_left + table.width - unit.width, unit_top))
    canvas.paste(table, (table_left, unit_top + unit.height + _UNIT_GAP))
    logger.info(
        "尺码图生成完成 output=%r unit=%s certificate_width=%d table_width=%d",
        str(output),
        size_unit,
        certificate.width,
        table.width,
    )
    return save_business_jpeg(canvas, output)
