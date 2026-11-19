from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageStat

from .font_assets import FontAsset, load_font_assets, require_glyphs
from .image_resize_compress import to_rgb
from .utils import add_warning


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OutfitDetail:
    """搭配模块末段的源图、裁切区域和销售备注。"""

    source: Path
    region: tuple[int, int, int, int] | None
    short_name: str
    blank_top: int | None = None


# 每组天猫切片由一张带备注的原模块替代，其余切片置空。
OutfitVariants = dict[Path, OutfitDetail | None]


def collect_outfit_variants(
    tmall_details: Path,
    report: dict,
    overrides: dict[Path, Path] | None,
) -> OutfitVariants:
    """根据天猫模块与输出切片的对应关系，准备带备注的派生模块。

    参数：
        tmall_details：天猫详情切片目录。
        report：包含模块计划记录和切片对应关系的报告。
        overrides：原图到已修正详情图的可选映射。
    返回值：
        以天猫切片路径为键的搭配备注替换计划。
    """
    replacements: OutfitVariants = {}
    corrected = {src.resolve(): dst for src, dst in (overrides or {}).items()}
    modules = report.get("详情页模块", {}).get("模块顺序", [])
    group_ends = {item["连续组"]: item for item in modules if item["类型"] == "搭配" and item["连续组"]}
    for item in modules:
        if "搭配备注" not in item:
            continue
        note = item["搭配备注"]
        name = note.get("品类短名") if isinstance(note, dict) else None
        source = Path(item["源图"])
        if group_ends.get(item["连续组"], item) is not item:
            logger.warning("搭配备注应标记在连续搭配的末段 source=%s", source)
            add_warning(report, "搭配备注应标记在连续搭配的末段", 源文件=str(source))
            continue
        if not isinstance(name, str) or not name.strip() or len(name.splitlines()) != 1:
            logger.warning("搭配备注缺少已确认的品类短名 source=%s", source)
            add_warning(report, "搭配备注需要确认当前商品的品类短名", 源文件=str(source))
            continue
        slices = item.get("搭配切片", [])
        if not slices:
            logger.warning("搭配模块没有可派生的天猫切片 source=%s", source)
            continue
        blank_top = note.get("留白起点")
        for filename in slices:
            replacements[tmall_details / filename] = None
        replacements[tmall_details / slices[0]] = OutfitDetail(
            corrected.get(source.resolve(), source),
            tuple(item["区域"]) if item["区域"] else None,
            name.strip(),
            blank_top if type(blank_top) is int and blank_top >= 0 else None,
        )
    return replacements


@lru_cache(maxsize=1)
def _note_font() -> FontAsset:
    """加载参考样式使用的方正兰亭中黑字形。"""
    return load_font_assets()["方正兰亭中黑"]


def _flat_background(region: Image.Image) -> tuple[int, int, int] | None:
    """读取浅色留白背景，避免把备注画在已有内容上。"""
    stats = ImageStat.Stat(region)
    if min(stats.median) < 200 or any(high - low > 22 for low, high in stats.extrema):
        return None
    return tuple(round(value) for value in stats.median)


def draw_outfit_note(image: Image.Image, note: OutfitDetail, source_height: int) -> Image.Image:
    """在搭配模块底部左对齐绘制销售备注，保留原画面。

    参数：
        image：按平台宽度缩放后的搭配模块。
        note：已确认短名及模块坐标系下的可选底部留白起点。
        source_height：未缩放的搭配模块高度，用于换算留白起点。
    返回值：
        带完整销售备注的 RGB 图像。
    """
    image = to_rgb(image)
    ratio = image.width / 790
    padding, gap, band_height = (max(1, round(value * ratio)) for value in (14, 20, 68))
    text = f"*注:仅售{note.short_name}，其余同款商品店内有售"
    asset = _note_font()
    require_glyphs(asset, text)
    size = max(1, round(24 * ratio))
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(str(asset.path), size)
    box = draw.textbbox((0, 0), text, font=font)
    while box[2] - box[0] > image.width - 2 * padding and size > max(1, round(18 * ratio)):
        size -= 1
        font = ImageFont.truetype(str(asset.path), size)
        box = draw.textbbox((0, 0), text, font=font)
    if box[2] - box[0] > image.width - 2 * padding:
        raise ValueError("销售备注超出一行，请确认品类短名")

    top = image.height
    background = None
    if note.blank_top is not None:
        candidate = round(note.blank_top * image.height / source_height)
        if candidate + gap < image.height:
            background = _flat_background(image.crop((0, candidate + gap, image.width, image.height)))
            if background is not None:
                top = candidate
    if background is None:
        background = _flat_background(image.crop((0, image.height - 1, image.width, image.height))) or (255, 255, 255)
    height = max(image.height, top + band_height)
    if height > image.height:
        canvas = Image.new("RGB", (image.width, height), background)
        canvas.paste(image, (0, 0))
        image = canvas
    ImageDraw.Draw(image).text((padding - box[0], top + gap - box[1]), text, font=font, fill=(120, 120, 120))
    logger.info("搭配销售备注明细 source=%s category=%s font_px=%d", note.source, note.short_name, size)
    return image
