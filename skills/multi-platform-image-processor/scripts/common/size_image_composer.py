from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image

from .certificate_composer import fit_contain, trim_white
from .utils import ensure_dir


logger = logging.getLogger(__name__)


def compose_size_image(certificate_image: Path, size_table: Path, output: Path) -> Path:
    """生成 800×800 合格证与尺码表组合图。

    参数：
        certificate_image：不含面料的 BarTender 导出图。
        size_table：完整实际尺码表裁切图。
        output：目标 JPG 路径。
    返回值：
        生成的尺码图路径。
    """
    with Image.open(certificate_image) as opened:
        certificate = fit_contain(trim_white(opened), (300, 260))
    with Image.open(size_table) as opened:
        table = fit_contain(trim_white(opened), (740, 450))
    canvas = Image.new("RGB", (800, 800), (255, 255, 255))
    gap = 28
    total_height = certificate.height + gap + table.height
    top = max(20, (800 - total_height) // 2)
    canvas.paste(certificate, ((800 - certificate.width) // 2, top))
    canvas.paste(table, ((800 - table.width) // 2, top + certificate.height + gap))
    ensure_dir(output.parent)
    canvas.save(output, "JPEG", quality=95, optimize=True)
    logger.info("尺码图生成完成 output=%r", str(output))
    return output
