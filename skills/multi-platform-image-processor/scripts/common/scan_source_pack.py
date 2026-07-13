from __future__ import annotations

from pathlib import Path

from .utils import list_images


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


def scan_source_pack(source_root: Path) -> dict:
    found: dict[str, dict] = {}
    missing: list[str] = []
    for name, rel in 源目录规则.items():
        path = resolve_source_path(source_root, name)
        images = list_images(path, recursive=(name == "素材图"))
        if path.exists():
            found[name] = {"目录": str(path), "图片数量": len(images)}
        else:
            missing.append(str(rel))
    return {"识别目录": found, "缺失目录": missing}


def get_image_group(source_root: Path, key: str, recursive: bool = False) -> list[Path]:
    return list_images(resolve_source_path(source_root, key), recursive=recursive)


def get_sku800(source_root: Path) -> list[Path]:
    explicit = get_image_group(source_root, "SKU800")
    if explicit:
        return explicit
    return get_image_group(source_root, "SKU")


def get_sku800_recursive(source_root: Path) -> list[Path]:
    explicit = get_image_group(source_root, "SKU800", recursive=True)
    if explicit:
        return explicit
    return get_image_group(source_root, "SKU", recursive=True)


def get_sku1440(source_root: Path) -> list[Path]:
    explicit = get_image_group(source_root, "SKU1440")
    if explicit:
        return explicit
    candidates = []
    for path in get_image_group(source_root, "SKU"):
        if "1440" in path.stem or "1440" in str(path.parent):
            candidates.append(path)
    return candidates
