from __future__ import annotations

from pathlib import Path

from common import list_images


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


def scan_source_pack(source_root: Path) -> dict:
    found: dict[str, dict] = {}
    missing: list[str] = []
    for name, rel in 源目录规则.items():
        path = source_root / rel
        images = list_images(path, recursive=(name == "素材图"))
        if path.exists():
            found[name] = {"目录": str(path), "图片数量": len(images), "图片": [str(p) for p in images]}
        else:
            missing.append(str(rel))
    return {"识别目录": found, "缺失目录": missing}


def get_image_group(source_root: Path, key: str, recursive: bool = False) -> list[Path]:
    rel = 源目录规则[key]
    return list_images(source_root / rel, recursive=recursive)


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
