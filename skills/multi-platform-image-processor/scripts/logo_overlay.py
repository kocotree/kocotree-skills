from __future__ import annotations

from pathlib import Path

from PIL import Image

from common import add_failure, add_risk
from image_resize_compress import open_image, save_jpg_under


def find_logo(template_root: Path | None) -> Path | None:
    if template_root is None or not template_root.exists():
        return None
    candidates = list(template_root.rglob("logo3.png"))
    return candidates[0] if candidates else None


def overlay_logo(source: Path, logo: Path | None, output: Path, max_bytes: int, report: dict, platform: str, usage: str) -> Path | None:
    try:
        base = open_image(source).convert("RGBA")
        if logo is None:
            add_risk(report, "未找到logo3.png，白底图＋logo按原图输出", 源文件=str(source))
            return save_jpg_under(base, output, max_bytes, report, source, platform, usage, ["未找到logo，按原图压缩"])
        mark = Image.open(logo).convert("RGBA")
        canvas = base.copy()
        canvas.alpha_composite(mark, (0, 0))
        return save_jpg_under(canvas, output, max_bytes, report, source, platform, usage, ["叠加logo3.png，位置和大小不调整"])
    except Exception as exc:
        add_failure(report, "叠加logo失败", 源文件=str(source), 输出文件=str(output), 错误=str(exc))
        return None
