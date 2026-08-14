from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from .certificate_composer import fit_contain, save_business_jpeg, trim_white

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


def extract_size_unit(source: Path, output: Path, content_box: CropBox) -> Path:
    """从详情源图提取尺码单位原始像素。

    参数：
        source：包含实际尺码表和单位的详情图。
        output：裁切后的单位图片路径。
        content_box：只包含尺码单位及必要留白的坐标。
    返回值：
        尺码单位图片路径。
    """
    with Image.open(source) as image:
        if not (
            0 <= content_box.left < content_box.right <= image.width
            and 0 <= content_box.top < content_box.bottom <= image.height
        ):
            raise RuntimeError(f"尺码单位裁切范围超出源图：{source}")
        unit = image.convert("RGB").crop(content_box.as_tuple())
    if unit.width < 8 or unit.height < 8:
        raise RuntimeError("尺码单位裁切区域过小")
    output.parent.mkdir(parents=True, exist_ok=True)
    unit.save(output, "PNG", optimize=True)
    logger.info("尺码单位提取完成 source=%r output=%r box=%r", str(source), str(output), content_box.as_tuple())
    return output


def compose_size_image(
    certificate_image: Path,
    size_table: Path,
    size_unit: Path,
    output: Path,
) -> Path:
    """生成 800×800 合格证与尺码表组合图。

    参数：
        certificate_image：不含面料的 BarTender 导出图。
        size_table：完整实际尺码表裁切图。
        size_unit：从详情源图裁取的尺码单位图。
        output：目标 JPG 路径。
    返回值：
        生成的尺码图路径。
    """
    with Image.open(certificate_image) as opened:
        certificate = fit_contain(trim_white(opened), (300, 260))
    with Image.open(size_table) as opened:
        original_table = trim_white(opened)
        table = fit_contain(original_table, (740, 420))
    with Image.open(size_unit) as opened:
        unit = trim_white(opened)
    scale = table.width / original_table.width
    unit = unit.resize(
        (
            max(1, round(unit.width * scale)),
            max(1, round(unit.height * scale)),
        ),
        Image.Resampling.LANCZOS,
    )
    unit = fit_contain(unit, (180, 48))
    canvas = Image.new("RGB", (800, 800), (255, 255, 255))
    certificate_gap = 28
    unit_gap = 8
    total_height = certificate.height + certificate_gap + unit.height + unit_gap + table.height
    top = max(20, (800 - total_height) // 2)
    canvas.paste(certificate, ((800 - certificate.width) // 2, top))
    table_left = (800 - table.width) // 2
    unit_top = top + certificate.height + certificate_gap
    canvas.paste(unit, (table_left + table.width - unit.width, unit_top))
    canvas.paste(table, (table_left, unit_top + unit.height + unit_gap))
    logger.info("尺码图生成完成 output=%r", str(output))
    return save_business_jpeg(canvas, output)
