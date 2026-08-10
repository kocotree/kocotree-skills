from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from .utils import list_images, natural_sort_key


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


def find_size_table_candidates(detail_root: Path) -> list[Path]:
    """按文件名线索和自然顺序列出尺码表候选图片。"""
    images = list_images(detail_root, recursive=True)
    keywords = ("尺码", "size", "规格", "参数")
    preferred = [path for path in images if any(word in path.stem.casefold() for word in keywords)]
    others = [path for path in images if path not in preferred]
    return sorted(preferred, key=natural_sort_key) + sorted(others, key=natural_sort_key)


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
