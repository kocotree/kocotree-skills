"""坐标网格参照图：在实物背景模特图上叠加像素网格与刻度，便于 agent 给准源图坐标。"""
from __future__ import annotations

from PIL import Image, ImageDraw

from core.utils import get_logger

logger = get_logger(__name__)


def draw_coordinate_grid(image: Image.Image, step: int | None = None) -> Image.Image:
    """在图像上叠加红色网格线与像素坐标刻度。

    参数:
        image: 源模特图。
        step: 网格间距像素；为 None 时按图像尺寸自动取值。
    返回:
        带网格与坐标标注的 RGB 图像。
    """
    base = image.convert("RGBA").copy()
    width, height = base.size
    if step is None:
        # 自动间距：约把短边分成 50 格，并取整到 50 的倍数。
        # 常见 5300px 源图会得到 100px 细网格，比旧版 250px 更适合读坐标。
        raw = max(50, round(min(width, height) / 50))
        step = int(round(raw / 50) * 50) or 50

    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    minor_line = (255, 0, 0, 75)
    major_line = (255, 0, 0, 210)
    major_step = step * 5

    for x in range(0, width, step):
        is_major = x % major_step == 0
        draw.line([(x, 0), (x, height)], fill=major_line if is_major else minor_line, width=2 if is_major else 1)
        if is_major:
            draw.text((x + 4, 4), str(x), fill=major_line)
    for y in range(0, height, step):
        is_major = y % major_step == 0
        draw.line([(0, y), (width, y)], fill=major_line if is_major else minor_line, width=2 if is_major else 1)
        if is_major:
            draw.text((4, y + 4), str(y), fill=major_line)
    return Image.alpha_composite(base, overlay).convert("RGB")
