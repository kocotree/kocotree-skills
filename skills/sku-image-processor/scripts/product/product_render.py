"""商品渲染：把透明商品图放进贴片区，并在绿色标签上绘制颜色名文字。

右侧贴片区位置在模板上完全固定，全部按 layout.json 中的坐标放置。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from core.config import WorkflowConfig
from core.geometry import trim_alpha
from core.utils import get_logger

logger = get_logger(__name__)


def place_product(layer: Image.Image, transparent_path: Path, cfg: WorkflowConfig) -> dict[str, Any]:
    """把透明商品图裁边、等比缩放后居中放到贴片商品区。

    参数:
        layer: 需要原地合成的图层（贴片/画布，RGBA）。
        transparent_path: 透明商品图路径（PNG）。
        cfg: 工作流配置（提供商品区坐标与最大高度）。
    返回:
        商品放置信息（源包围盒、贴入包围盒、缩放系数）。
    """
    product = Image.open(transparent_path).convert("RGBA")
    trimmed, bbox = trim_alpha(product)
    box = cfg.layout.product_box
    max_width = box[2] - box[0]
    max_height = box[3] - box[1]
    # 取三者最小值：宽度受限、商品区高度受限、配置的商品最大高度受限
    scale = min(max_width / trimmed.width, max_height / trimmed.height, cfg.product_max_height / trimmed.height)
    width = round(trimmed.width * scale)
    height = round(trimmed.height * scale)
    resized = trimmed.resize((width, height), Image.Resampling.LANCZOS)
    x = box[0] + (max_width - width) // 2
    y = box[1] + (max_height - height) // 2
    layer.alpha_composite(resized, (x, y))
    logger.info("商品图放置完成: %s 缩放=%.3f", transparent_path.name, scale)
    return {
        "source_alpha_bbox": list(bbox),
        "placed_bbox": [x, y, x + width, y + height],
        "scale": scale,
    }


def draw_label(layer: Image.Image, text: str, cfg: WorkflowConfig, font_path: Path) -> dict[str, Any]:
    """在标签文字区居中绘制颜色名（白色字）。

    参数:
        layer: 需要原地绘制的图层（RGBA）。
        text: 颜色名文字。
        cfg: 工作流配置（提供文字框坐标）。
        font_path: 字体文件路径。
    返回:
        标签绘制信息（字体、字号、文字包围盒）。
    """
    font, font_size, text_bbox = _fit_font(text, cfg, font_path)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]
    box = cfg.layout.text_box
    x = box[0] + ((box[2] - box[0]) - text_width) // 2 - text_bbox[0]
    y = box[1] + ((box[3] - box[1]) - text_height) // 2 - text_bbox[1] - 2
    ImageDraw.Draw(layer).text((x, y), text, font=font, fill=(255, 255, 255, 255))
    return {
        "font": str(font_path),
        "font_size": font_size,
        "text_bbox": [x + text_bbox[0], y + text_bbox[1], x + text_bbox[2], y + text_bbox[3]],
    }


def _fit_font(
    text: str, cfg: WorkflowConfig, font_path: Path
) -> tuple[ImageFont.FreeTypeFont, int, tuple[int, int, int, int]]:
    """从大到小尝试字号，找到能放进文字框的最大字号。

    参数:
        text: 待排版文字。
        cfg: 工作流配置（提供文字框坐标）。
        font_path: 字体文件路径。
    返回:
        (字体对象, 字号, 文字包围盒)。都放不下时退回最小字号 24。
    """
    box = cfg.layout.text_box
    max_width = box[2] - box[0] - 24   # 预留左右内边距
    max_height = box[3] - box[1] - 10  # 预留上下内边距
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    for font_size in range(64, 23, -2):
        font = ImageFont.truetype(str(font_path), font_size)
        bbox = probe.textbbox((0, 0), text, font=font)
        if bbox[2] - bbox[0] <= max_width and bbox[3] - bbox[1] <= max_height:
            return font, font_size, bbox
    font = ImageFont.truetype(str(font_path), 24)
    logger.warning("颜色名 '%s' 在最小字号下仍可能超框", text)
    return font, 24, probe.textbbox((0, 0), text, font=font)
