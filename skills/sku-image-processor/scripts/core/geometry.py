"""几何工具：透明图裁边与空布局生成。

本模块只做与具体商品无关的通用几何运算。
"""
from __future__ import annotations

from typing import Any

from PIL import Image


def trim_alpha(image: Image.Image) -> tuple[Image.Image, tuple[int, int, int, int]]:
    """按 alpha 通道裁掉透明边，返回裁剪后的图和原始非透明包围盒。

    参数:
        image: RGBA 图像。
    返回:
        (裁剪后的图, 原图中的非透明包围盒)；全透明时返回原图与整图尺寸。
    """
    bbox = image.getchannel("A").getbbox()
    if not bbox:
        return image, (0, 0, image.width, image.height)
    return image.crop(bbox), bbox


def empty_layout(mode: str) -> dict[str, Any]:
    """构造一个不含人物的空布局（用于只有透明商品图、无模特图的情况）。

    参数:
        mode: 布局模式标识，如 "transparent_only"。
    返回:
        空布局字典。
    """
    return {
        "mode": mode,
        "background_extended": False,
        "decision": mode,
        "boxes": {},
    }
