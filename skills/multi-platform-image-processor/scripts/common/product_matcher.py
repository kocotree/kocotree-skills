from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, TypeVar

from .nas_paths import list_files_fast


T = TypeVar("T")


@dataclass(frozen=True)
class MatchResult:
    """描述唯一匹配或候选冲突。"""

    selected: object | None
    candidates: list[object] = field(default_factory=list)
    reason: str = ""

    @property
    def unique(self) -> bool:
        """返回匹配结果是否唯一。"""
        return self.selected is not None and len(self.candidates) == 1


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


def select_unique(
    candidates: Iterable[T],
    product_code: str,
    product_name: str = "",
    text_getter=lambda item: str(item),
) -> MatchResult:
    """按货号精确匹配并使用产品名称复核。

    参数：
        candidates：待筛选对象。
        product_code：必须精确匹配的产品货号。
        product_name：用于复核的产品名称。
        text_getter：从候选对象提取可匹配文本的函数。
    返回值：
        唯一结果、候选列表和匹配说明。
    """
    code_matches = [
        item for item in candidates
        if contains_exact_code(text_getter(item), product_code)
    ]
    if product_name:
        normalized_name = normalize_identity(product_name)
        name_matches = [
            item for item in code_matches
            if normalized_name and normalized_name in normalize_identity(text_getter(item))
        ]
        if name_matches:
            code_matches = name_matches
    if len(code_matches) == 1:
        return MatchResult(code_matches[0], list(code_matches), "货号精确匹配且候选唯一")
    if not code_matches:
        return MatchResult(None, [], "没有找到货号精确匹配项")
    return MatchResult(None, list(code_matches), "存在多个候选，不能自动选择")


def extract_size(text: str) -> int | None:
    """从文件名或标签中提取常见数字尺码。"""
    sizes = [int(value) for value in re.findall(r"(?<!\d)(\d{2,3})(?!\d)", text)]
    plausible = [value for value in sizes if 40 <= value <= 220]
    return plausible[-1] if plausible else None


def select_representative_size(paths: Iterable[Path], preferred: int = 110) -> MatchResult:
    """选择代表尺码文件。

    参数：
        paths：同一产品和颜色的候选文件。
        preferred：优先尺码，默认 110。
    返回值：
        选中的文件、全部有效候选和选择说明。
    """
    sized = [(path, extract_size(path.stem)) for path in paths]
    valid = [(path, size) for path, size in sized if size is not None]
    preferred_items = [path for path, size in valid if size == preferred]
    if len(preferred_items) == 1:
        return MatchResult(preferred_items[0], [path for path, _ in valid], f"选择优先尺码 {preferred}")
    if len(preferred_items) > 1:
        return MatchResult(None, preferred_items, f"尺码 {preferred} 存在多个候选")
    if not valid:
        return MatchResult(None, [], "候选文件中没有可识别尺码")
    smallest = min(size for _, size in valid)
    smallest_items = [path for path, size in valid if size == smallest]
    if len(smallest_items) == 1:
        return MatchResult(smallest_items[0], [path for path, _ in valid], f"没有 {preferred} 码，选择最小尺码 {smallest}")
    return MatchResult(None, smallest_items, f"最小尺码 {smallest} 存在多个候选")


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
