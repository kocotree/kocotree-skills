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
        payload = re.sub(
            r"^(?:面料|材质|成分)\s*[:：]\s*",
            "",
            normalize_parentheses(fabric_text.strip()),
        )
        text = f"面料：{payload}"
        maximum_width = subject.width - fabric_anchor[0] - 12
        if maximum_width <= font_size * 2:
            raise RuntimeError("合格证面料锚点右侧空间不足")
        lines = wrap_mixed_text(text, fabric_fonts, font_size, maximum_width)
        line_height = mixed_line_height(text, fabric_fonts, font_size, 8)
        if fabric_anchor[1] + line_height * len(lines) > subject.height:
            raise RuntimeError("合格证面料文字超出主体底部")
        style = TextStyle(font_size, (20, 20, 20), 8)
        for line_index, line in enumerate(lines):
            if line:
                draw_mixed_text(
                    subject,
                    (fabric_anchor[0], fabric_anchor[1] + line_index * line_height),
                    line,
                    fabric_fonts,
                    style,
                )
    if not dealer_address_image.is_file():
        raise RuntimeError(f"合格证经销商地址图片不存在：{dealer_address_image}")
    with Image.open(dealer_address_image) as opened:
        dealer_address = fit_contain(opened.convert("RGB"), _DEALER_ADDRESS_MAXIMUM)
    available_subject_height = (
        _CERTIFICATE_CONTENT_MAXIMUM[1] - dealer_address.height - _DEALER_ADDRESS_GAP
    )
    fitted = fit_contain(
        subject,
        (_CERTIFICATE_CONTENT_MAXIMUM[0], available_subject_height),
    )
    content = Image.new(
        "RGB",
        (
            max(fitted.width, dealer_address.width),
            fitted.height + _DEALER_ADDRESS_GAP + dealer_address.height,
        ),
        (255, 255, 255),
    )
    content.paste(fitted, (0, 0))
    content.paste(dealer_address, (0, fitted.height + _DEALER_ADDRESS_GAP))
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
