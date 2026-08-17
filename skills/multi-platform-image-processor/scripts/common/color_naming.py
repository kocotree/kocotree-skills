from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .scan_source_pack import (
    get_image_group,
    get_sku800_recursive,
    has_gift_sku_branches,
    resolve_sku_root,
)


logger = logging.getLogger(__name__)


def _sku_names_for_color_assets(source_root: Path) -> set[str]:
    """返回白底图和透明图可使用的 SKU 规格名称。

    功能说明：普通 SKU 使用全部 800 图；赠品 SKU 仅使用无赠品 800 图，
    避免把赠品说明写入白底图或透明图文件名。
    参数：
        source_root：产品素材根目录。
    返回值：
        可用于颜色素材命名的 SKU 规格名称集合。
    """
    sources = get_sku800_recursive(source_root)
    if has_gift_sku_branches(source_root):
        sku_root = resolve_sku_root(source_root)
        sources = [
            source for source in sources
            if "无赠品" in {
                part.replace(" ", "")
                for part in source.relative_to(sku_root).parts
            }
        ]
    return {source.stem for source in sources}


def resolve_color_names(
    source_root: Path,
    raw_mapping: Any,
) -> dict[Path, str]:
    """解析白底图、透明图与 SKU 颜色名称的对应关系。

    功能说明：直接使用已按颜色命名的源图；数字等无颜色文件名依据
    Agent 视觉映射关联到 SKU 名称，并确保同组输出名称唯一。
    参数：
        source_root：产品素材根目录。
        raw_mapping：相对图片路径到 SKU 颜色名称的映射。
    返回值：
        源图片绝对路径到颜色名称的映射。
    """
    sku_names = _sku_names_for_color_assets(source_root)
    if not sku_names:
        raise RuntimeError("缺少可用于颜色命名的 SKU 图片")
    supplied = {
        str(key).replace("\\", "/"): str(value).strip()
        for key, value in (raw_mapping.items() if isinstance(raw_mapping, dict) else [])
    }
    resolved: dict[Path, str] = {}
    for group in ("白底图", "透明图"):
        used: set[str] = set()
        for source in get_image_group(source_root, group):
            relative = source.relative_to(source_root).as_posix()
            color = source.stem if source.stem in sku_names else supplied.get(relative, "")
            if not color:
                raise RuntimeError(f"缺少{group}与 SKU 颜色的视觉对应关系：{relative}")
            if color not in sku_names:
                raise RuntimeError(f"{group}颜色名称不在 SKU 文件名中：{relative} -> {color}")
            if color in used:
                raise RuntimeError(f"{group}颜色名称重复：{color}")
            used.add(color)
            resolved[source.resolve()] = color
            logger.info("颜色命名匹配完成 source=%r color=%s", str(source), color)
    return resolved


def color_output_name(
    source: Path,
    color_names: dict[Path, str],
    suffix: str,
) -> str:
    """返回一张白底图或透明图的颜色文件名。"""
    color = color_names.get(source.resolve())
    if not color:
        raise RuntimeError(f"图片缺少 SKU 颜色名称：{source}")
    return f"{color}{suffix}"
