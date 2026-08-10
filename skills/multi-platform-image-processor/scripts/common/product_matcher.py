from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .nas_paths import list_files_fast


@dataclass(frozen=True)
class MatchResult:
    """描述唯一匹配或候选冲突。"""

    selected: object | None
    candidates: list[object] = field(default_factory=list)
    reason: str = ""

def normalize_identity(value: object) -> str:
    """归一化产品身份文本，保留 Unicode 字母和数字。"""
    return "".join(character for character in str(value) if character.isalnum()).casefold()


def contains_exact_code(text: object, product_code: str) -> bool:
    """判断文本是否包含边界明确的产品货号。"""
    code = str(product_code).strip()
    if not code:
        return False
    pattern = rf"(?<![0-9A-Za-z]){re.escape(code)}(?![0-9A-Za-z])"
    return re.search(pattern, str(text), flags=re.IGNORECASE) is not None


def infer_product_code(source: Path) -> str:
    """从产品目录名称中识别产品货号。

    参数：
        source：产品目录或数据包目录。
    返回值：
        识别到的产品货号；无法可靠识别时返回空字符串。
    """
    product_dir = source.parent if source.name == "数据包" else source
    matches = re.findall(
        r"(?<![0-9A-Za-z])([A-Za-z][A-Za-z0-9_-]*\d[A-Za-z0-9_-]*)(?![0-9A-Za-z])",
        product_dir.name,
    )
    unique = list(dict.fromkeys(match.upper() for match in matches))
    return unique[0] if len(unique) == 1 else ""


def extract_size(text: str) -> int | None:
    """从文件名或标签中提取常见数字尺码。"""
    sizes = [int(value) for value in re.findall(r"(?<!\d)(\d{2,3})(?!\d)", text)]
    plausible = [value for value in sizes if 40 <= value <= 220]
    return plausible[-1] if plausible else None


def select_bartender_file(
    root: Path,
    product_code: str,
    product_name: str = "",
    color: str = "",
    preferred_size: int = 110,
) -> MatchResult:
    """匹配产品并选择一份代表 BarTender 文件。

    参数：
        root：合格证文件根目录。
        product_code：精确匹配的产品货号。
        product_name：用于复核的产品名称。
        color：用户指定的代表颜色。
        preferred_size：优先尺码。
    返回值：
        选中文件、产品候选和选择说明。
    """
    candidates = sorted(
        (
            path for path in list_files_fast(root, {".btw"}, product_code)
            if contains_exact_code(str(path.relative_to(root)), product_code)
        ),
        key=lambda path: path.as_posix().casefold(),
    )
    if not candidates:
        candidates = sorted(
            (
                path for path in list_files_fast(root, {".btw"})
                if contains_exact_code(str(path.relative_to(root)), product_code)
            ),
            key=lambda path: path.as_posix().casefold(),
        )
    if product_name:
        name_key = normalize_identity(product_name)
        named = [path for path in candidates if name_key in normalize_identity(path)]
        if not named:
            return MatchResult(None, candidates, "货号候选与产品名称不一致")
        candidates = named
    if color:
        color_key = normalize_identity(color)
        colored = [path for path in candidates if color_key in normalize_identity(path)]
        if not colored:
            return MatchResult(None, candidates, f"没有找到指定颜色 {color} 的 BarTender 文件")
        candidates = colored
    sized = [(path, extract_size(path.stem)) for path in candidates]
    valid = [(path, size) for path, size in sized if size is not None]
    if not valid:
        return MatchResult(None, candidates, "BarTender 候选中没有可识别尺码")
    target_size = preferred_size if any(size == preferred_size for _, size in valid) else min(
        size for _, size in valid
    )
    target = [path for path, size in valid if size == target_size]
    if len(target) == 1:
        reason = f"选择优先尺码 {target_size}" if target_size == preferred_size else f"选择最小尺码 {target_size}"
        return MatchResult(target[0], candidates, reason)
    if color:
        return MatchResult(None, target, f"指定颜色的尺码 {target_size} 存在多个候选")
    reason = f"未指定颜色，按自然顺序选择尺码 {target_size} 的首个代表候选"
    return MatchResult(target[0], candidates, reason)
