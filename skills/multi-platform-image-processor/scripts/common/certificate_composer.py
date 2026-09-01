from __future__ import annotations

import io
import logging
import re
from pathlib import Path

from PIL import Image, ImageChops

from .font_assets import FontAsset
from .material_editor import (
    TextStyle,
    draw_mixed_text,
    mixed_line_height,
    normalize_parentheses,
    wrap_mixed_text,
)
from .utils import ensure_dir


logger = logging.getLogger(__name__)

_DEALER_ADDRESS_MAXIMUM = (450, 100)
_DEALER_ADDRESS_GAP = 30
_CERTIFICATE_CONTENT_MAXIMUM = (650, 1250)
_FALLBACK_FABRIC_FONT_SIZE = 20
_FALLBACK_FABRIC_LINE_SPACING = 6
_FALLBACK_FABRIC_TOP_GAP = 24
_FALLBACK_DEALER_GAP = 6


def format_certificate_fabric_text(fabric_text: str) -> str:
    """整理合格证需要绘制的面料文字。

    功能说明：统一中英文括号；原文已包含带冒号的层级名称时直接保留，
    只有纯成分文本才补充“面料：”前缀。
    参数：
        fabric_text：产品信息 Excel 中的中文面料原文。
    返回值：
        适合绘制到合格证的信息文本。
    """
    normalized = normalize_parentheses(fabric_text.strip())
    if re.match(r"^[^\n：:]{1,12}[：:]", normalized):
        return normalized
    return f"面料：{normalized}"


def _prepare_fabric_layout(
    subject: Image.Image,
    text: str,
    anchor: tuple[int, int],
    fonts: dict[str, FontAsset],
    font_size: int,
) -> tuple[list[str], int]:
    """计算合格证面料在指定锚点的排版。

    功能说明：按可用宽高对面料换行，并确认完整文字位于合格证主体内。
    参数：
        subject：裁去外围白边后的合格证主体。
        text：准备写入的面料文字。
        anchor：文字左上角坐标。
        fonts：混合字体角色映射。
        font_size：面料字号。
    返回值：
        换行结果和单行高度。
    """
    if anchor[0] < 0 or anchor[1] < 0:
        raise RuntimeError("合格证面料锚点不能为负数")
    maximum_width = subject.width - anchor[0] - 12
    if maximum_width <= font_size * 2:
        raise RuntimeError("合格证面料锚点右侧空间不足")
    lines = wrap_mixed_text(text, fonts, font_size, maximum_width)
    line_height = mixed_line_height(text, fonts, font_size, 8)
    if anchor[1] + line_height * len(lines) > subject.height:
        raise RuntimeError("合格证面料文字超出主体底部")
    return lines, line_height


def _draw_fabric_text(
    subject: Image.Image,
    lines: list[str],
    anchor: tuple[int, int],
    fonts: dict[str, FontAsset],
    font_size: int,
    line_height: int,
    line_spacing: int = 8,
) -> None:
    """按已确认布局绘制合格证面料文字。"""
    style = TextStyle(font_size, (20, 20, 20), line_spacing)
    for line_index, line in enumerate(lines):
        if line:
            draw_mixed_text(
                subject,
                (anchor[0], anchor[1] + line_index * line_height),
                line,
                fonts,
                style,
            )


def trim_white(image: Image.Image, threshold: int = 250) -> Image.Image:
    """裁掉图片外围接近纯白的空白区域。"""
    rgb = image.convert("RGB")
    background = Image.new("RGB", rgb.size, (255, 255, 255))
    difference = ImageChops.difference(rgb, background).convert("L")
    mask = difference.point(lambda value: 255 if value > 255 - threshold else 0)
    box = mask.getbbox()
    return rgb.crop(box) if box else rgb


def fit_contain(image: Image.Image, maximum: tuple[int, int]) -> Image.Image:
    """将图片等比例缩放到指定最大尺寸。"""
    copy = image.copy()
    copy.thumbnail(maximum, Image.Resampling.LANCZOS)
    return copy


def save_business_jpeg(canvas: Image.Image, output: Path, max_bytes: int = 500 * 1024) -> Path:
    """将固定画布保存为符合业务大小限制的 JPG。

    参数：
        canvas：需要保存的完整业务图片画布。
        output：固定输出文件路径。
        max_bytes：允许的最大文件字节数。
    返回值：
        符合大小限制的 JPG 路径。
    """
    ensure_dir(output.parent)
    rgb = canvas.convert("RGB")
    for quality in list(range(95, 9, -5)) + [5]:
        buffer = io.BytesIO()
        rgb.save(buffer, "JPEG", quality=quality, optimize=True, progressive=True)
        data = buffer.getvalue()
        if len(data) <= max_bytes:
            output.write_bytes(data)
            logger.info(
                "业务图片保存完成 output=%r quality=%d size_kb=%.2f",
                str(output),
                quality,
                len(data) / 1024,
            )
            return output
    raise RuntimeError(f"业务图片无法压缩到 {max_bytes / 1024:.0f}KB：{output}")


def compose_certificate(
    exported_image: Path,
    output: Path,
    dealer_address_image: Path,
    fabric_text: str = "",
    fabric_anchor: tuple[int, int] | None = None,
    fabric_fonts: dict[str, FontAsset] | None = None,
    font_size: int = 34,
) -> Path:
    """生成 750×1600 合格证图。

    参数：
        exported_image：BarTender 导出的合格证图片。
        output：目标 JPG 路径。
        dealer_address_image：固定经销商与地址图片。
        fabric_text：可选的中文面料原文。
        fabric_anchor：面料在导出图坐标中的左上锚点。
        fabric_fonts：合格证面料使用的字体角色映射。
        font_size：面料字号。
    返回值：
        生成的合格证图路径。
    """
    with Image.open(exported_image) as opened:
        subject = trim_white(opened)
    if fabric_text:
        if fabric_anchor is None or fabric_fonts is None:
            raise RuntimeError("合格证加入面料时必须提供“等级”下方锚点和字体")
        text = format_certificate_fabric_text(fabric_text)
        fallback_lines: list[str] | None = None
        try:
            lines, line_height = _prepare_fabric_layout(
                subject,
                text,
                fabric_anchor,
                fabric_fonts,
                font_size,
            )
            _draw_fabric_text(
                subject,
                lines,
                fabric_anchor,
                fabric_fonts,
                font_size,
                line_height,
            )
        except RuntimeError as primary_error:
            fallback_lines = wrap_mixed_text(
                text,
                fabric_fonts,
                _FALLBACK_FABRIC_FONT_SIZE,
                _CERTIFICATE_CONTENT_MAXIMUM[0],
            )
            logger.warning(
                "合格证等级下方无法容纳面料，使用价格下方固定布局 reason=%s",
                primary_error,
            )
    else:
        fallback_lines = None
    if not dealer_address_image.is_file():
        raise RuntimeError(f"合格证经销商地址图片不存在：{dealer_address_image}")
    with Image.open(dealer_address_image) as opened:
        dealer_address = fit_contain(opened.convert("RGB"), _DEALER_ADDRESS_MAXIMUM)
    if fallback_lines:
        fallback_line_height = mixed_line_height(
            text,
            fabric_fonts,
            _FALLBACK_FABRIC_FONT_SIZE,
            _FALLBACK_FABRIC_LINE_SPACING,
        )
        fallback_height = fallback_line_height * len(fallback_lines)
        trailing_height = (
            _FALLBACK_FABRIC_TOP_GAP
            + fallback_height
            + _FALLBACK_DEALER_GAP
            + dealer_address.height
        )
    else:
        fallback_line_height = 0
        fallback_height = 0
        trailing_height = _DEALER_ADDRESS_GAP + dealer_address.height
    available_subject_height = _CERTIFICATE_CONTENT_MAXIMUM[1] - trailing_height
    if available_subject_height <= 0:
        raise RuntimeError("合格证面料和经销商地址超出内容区")
    fitted = fit_contain(
        subject,
        (_CERTIFICATE_CONTENT_MAXIMUM[0], available_subject_height),
    )
    content_height = fitted.height + trailing_height
    content = Image.new(
        "RGB",
        (
            max(fitted.width, dealer_address.width),
            content_height,
        ),
        (255, 255, 255),
    )
    content.paste(fitted, (0, 0))
    if fallback_lines:
        fabric_top = fitted.height + _FALLBACK_FABRIC_TOP_GAP
        _draw_fabric_text(
            content,
            fallback_lines,
            (0, fabric_top),
            fabric_fonts,
            _FALLBACK_FABRIC_FONT_SIZE,
            fallback_line_height,
            _FALLBACK_FABRIC_LINE_SPACING,
        )
        dealer_top = fabric_top + fallback_height + _FALLBACK_DEALER_GAP
    else:
        dealer_top = fitted.height + _DEALER_ADDRESS_GAP
    content.paste(dealer_address, (0, dealer_top))
    canvas = Image.new("RGB", (750, 1600), (255, 255, 255))
    position = ((750 - content.width) // 2, (1600 - content.height) // 2)
    canvas.paste(content, position)
    logger.info(
        "合格证图生成完成 output=%r dealer_address=%r",
        str(output),
        str(dealer_address_image),
    )
    return save_business_jpeg(canvas, output)


def compose_hangtag(exported_image: Path, output: Path) -> Path:
    """生成不含面料的 800×800 吊牌图。

    参数：
        exported_image：BarTender 导出的合格证图片。
        output：目标 JPG 路径。
    返回值：
        生成的吊牌图路径。
    """
    with Image.open(exported_image) as opened:
        subject = fit_contain(trim_white(opened), (720, 720))
    canvas = Image.new("RGB", (800, 800), (255, 255, 255))
    canvas.paste(subject, ((800 - subject.width) // 2, (800 - subject.height) // 2))
    logger.info("吊牌图生成完成 output=%r", str(output))
    return save_business_jpeg(canvas, output)
