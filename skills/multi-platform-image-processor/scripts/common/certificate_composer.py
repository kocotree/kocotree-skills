from __future__ import annotations

import io
import logging
import re
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

from .font_assets import FontAsset, require_glyphs
from .utils import ensure_dir


logger = logging.getLogger(__name__)


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
    fabric_text: str = "",
    fabric_anchor: tuple[int, int] | None = None,
    fabric_font: FontAsset | None = None,
    font_size: int = 34,
) -> Path:
    """生成 750×1600 合格证图。

    参数：
        exported_image：BarTender 导出的合格证图片。
        output：目标 JPG 路径。
        fabric_text：可选的中文面料原文。
        fabric_anchor：面料在导出图坐标中的左上锚点。
        fabric_font：合格证面料使用的方正字体。
        font_size：面料字号。
    返回值：
        生成的合格证图路径。
    """
    with Image.open(exported_image) as opened:
        subject = trim_white(opened)
    if fabric_text:
        if fabric_anchor is None or fabric_font is None:
            raise RuntimeError("合格证加入面料时必须提供“等级”下方锚点和方正字体")
        payload = re.sub(r"^(?:面料|材质|成分)\s*[:：]\s*", "", fabric_text.strip())
        text = f"面料：{payload}"
        require_glyphs(fabric_font, text)
        draw = ImageDraw.Draw(subject)
        font = ImageFont.truetype(str(fabric_font.path), font_size)
        maximum_width = subject.width - fabric_anchor[0] - 12
        if maximum_width <= font_size * 2:
            raise RuntimeError("合格证面料锚点右侧空间不足")
        lines: list[str] = []
        current = ""
        for character in text:
            if character == "\n":
                if current:
                    lines.append(current)
                current = ""
                continue
            candidate = current + character
            if current and draw.textlength(candidate, font=font) > maximum_width:
                lines.append(current)
                current = character
            else:
                current = candidate
        if current:
            lines.append(current)
        line_height = font.getbbox("中文Ag")[3] - font.getbbox("中文Ag")[1] + 8
        if fabric_anchor[1] + line_height * len(lines) > subject.height:
            raise RuntimeError("合格证面料文字超出主体底部")
        draw.multiline_text(
            fabric_anchor,
            "\n".join(lines),
            font=font,
            fill=(20, 20, 20),
            spacing=8,
        )
    fitted = fit_contain(subject, (650, 1250))
    canvas = Image.new("RGB", (750, 1600), (255, 255, 255))
    position = ((750 - fitted.width) // 2, (1600 - fitted.height) // 2)
    canvas.paste(fitted, position)
    logger.info("合格证图生成完成 output=%r", str(output))
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
