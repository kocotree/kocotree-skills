from __future__ import annotations

import logging
from pathlib import Path

from .utils import list_images


SKU赠品分支 = {"加赠品", "无赠品"}
SKU组合目录 = "sku组合"
SKU尺寸目录 = {"800", "800x800", "1400", "1440"}

logger = logging.getLogger(__name__)


源目录规则 = {
    "主图800": Path("主图") / "800",
    "主图1440": Path("主图") / "1440",
    "主图750": Path("主图") / "750",
    "SKU": Path("SKU"),
    "SKU800": Path("SKU") / "800",
    "SKU1440": Path("SKU") / "1440",
    "白底图": Path("白底图"),
    "透明图": Path("透明图"),
    "详情静态": Path("详情") / "静态",
    "详情上": Path("详情") / "静态" / "上",
    "详情下": Path("详情") / "静态" / "下",
    "素材图": Path("素材图"),
}


def resolve_source_path(source_root: Path, key: str) -> Path:
    """解析标准素材目录，并允许 SKU 根目录使用任意大小写。

    参数：
        source_root：数据包根目录。
        key：`源目录规则` 中的素材分组名称。
    返回值：
        当前文件系统中实际使用的素材目录路径。
    """
    rel = 源目录规则[key]
    if not rel.parts or rel.parts[0].casefold() != "sku":
        return source_root / rel
    sku_root = resolve_sku_root(source_root)
    return sku_root.joinpath(*rel.parts[1:])


def resolve_sku_root(source_root: Path) -> Path:
    """以不区分大小写的方式定位 SKU 根目录。

    参数：
        source_root：数据包根目录。
    返回值：
        唯一匹配的 SKU 根目录；未找到时返回标准路径 `SKU`。
    """
    standard = source_root / "SKU"
    if not source_root.exists():
        return standard
    matches = [
        child for child in source_root.iterdir()
        if child.is_dir() and child.name.casefold() == "sku"
    ]
    if len(matches) == 1:
        return matches[0]
    return standard


def has_gift_sku_branches(source_root: Path) -> bool:
    """判断 SKU 是否采用赠品分支结构。

    功能说明：检查 SKU 根目录的直接子目录是否包含“加赠品”或“无赠品”。
    参数：
        source_root：产品素材根目录。
    返回值：
        存在赠品分支时返回 True，否则返回 False。
    """
    sku_root = resolve_sku_root(source_root)
    if not sku_root.is_dir():
        return False
    branch_names = {
        child.name.replace(" ", "")
        for child in sku_root.iterdir()
        if child.is_dir()
    }
    return bool(branch_names.intersection(SKU赠品分支))


def normalize_sku_directory_name(name: str) -> str:
    """规范 SKU 目录名供尺寸和业务分支判断。"""
    return name.casefold().replace("×", "x").replace(" ", "")


def is_sku_size_directory(name: str) -> bool:
    """判断目录名是否表示 SKU 图片尺寸。"""
    return normalize_sku_directory_name(name) in SKU尺寸目录


def has_sku_business_branches(source_root: Path) -> bool:
    """判断 SKU 根目录是否包含尺寸目录之外的业务分支。"""
    sku_root = resolve_sku_root(source_root)
    if not sku_root.is_dir():
        return False
    return any(
        child.is_dir()
        and not is_sku_size_directory(child.name)
        and normalize_sku_directory_name(child.name) != SKU组合目录
        for child in sku_root.iterdir()
    )


def get_image_group(source_root: Path, key: str, recursive: bool = False) -> list[Path]:
    return list_images(resolve_source_path(source_root, key), recursive=recursive)


def get_sku800(source_root: Path) -> list[Path]:
    explicit = get_image_group(source_root, "SKU800")
    if explicit:
        return explicit
    return get_image_group(source_root, "SKU")


def get_sku800_recursive(source_root: Path) -> list[Path]:
    """递归读取 SKU 树中的 800 图。

    功能说明：识别任意业务分支下的 `800` 或 `800x800` 尺寸目录；
    没有尺寸目录的分支图片按 800 素材处理。组合 SKU 单独读取。
    参数：
        source_root：产品素材根目录。
    返回值：
        SKU 800 图片列表。
    """
    sku_root = resolve_sku_root(source_root)
    sources = list_images(sku_root, recursive=True)
    sized = []
    unsized = []
    for source in sources:
        relative = source.relative_to(sku_root)
        normalized_parts = {normalize_sku_directory_name(part) for part in relative.parent.parts}
        if SKU组合目录 in normalized_parts:
            continue
        if normalized_parts.intersection({"800", "800x800"}):
            sized.append(source)
        elif not any(is_sku_size_directory(part) for part in relative.parent.parts):
            unsized.append(source)
    selected = list(dict.fromkeys([*sized, *unsized]))
    logger.info(
        "SKU 800素材收集完成 sized=%d unsized=%d total=%d",
        len(sized),
        len(unsized),
        len(selected),
    )
    return selected


def get_combination_sku(source_root: Path) -> list[Path]:
    """读取 SKU 根目录下的组合 SKU 图片。

    功能说明：定位名为 `SKU组合` 的直接子目录并递归读取其中图片。
    参数：
        source_root：产品素材根目录。
    返回值：
        组合 SKU 图片列表；目录不存在时返回空列表。
    """
    sku_root = resolve_sku_root(source_root)
    if not sku_root.is_dir():
        return []
    directories = [
        child
        for child in sku_root.iterdir()
        if child.is_dir() and child.name.casefold().replace(" ", "") == SKU组合目录
    ]
    return [source for directory in directories for source in list_images(directory, recursive=True)]


def get_sku1440(source_root: Path) -> list[Path]:
    explicit = get_image_group(source_root, "SKU1440")
    if explicit:
        return explicit
    candidates = []
    for path in get_image_group(source_root, "SKU"):
        if "1440" in path.stem or "1440" in str(path.parent):
            candidates.append(path)
    return candidates
