from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path


logger = logging.getLogger(__name__)


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
    product_name: str,
    color: str,
    preferred_size: int = 110,
) -> MatchResult:
    """匹配产品并选择一份代表 BarTender 文件。

    参数：
        root：合格证文件根目录。
        product_name：产品信息 Excel 中的正式产品名称。
        color：产品信息 Excel 中确定的代表颜色。
        preferred_size：优先尺码。
    返回值：
        选中文件、产品候选和选择说明。
    """
    logger.info(
        "开始匹配 BarTender product=%r color=%r root=%r",
        product_name,
        color,
        str(root),
    )
    name_key = normalize_identity(product_name)
    if not name_key:
        return MatchResult(None, [], "产品信息 Excel 缺少正式产品名称")
    product_directories = sorted(
        (
            path for path in root.iterdir()
            if path.is_dir() and normalize_identity(path.name) == name_key
        ),
        key=lambda path: path.name.casefold(),
    )
    if not product_directories:
        return MatchResult(None, [], f"没有找到产品名称对应的合格证目录：{product_name}")
    if len(product_directories) > 1:
        return MatchResult(None, product_directories, f"产品名称对应多个合格证目录：{product_name}")

    product_directory = product_directories[0]
    logger.info("已匹配合格证产品目录 path=%r", str(product_directory))
    candidates = sorted(
        (
            path for path in product_directory.iterdir()
            if path.is_file() and path.suffix.casefold() == ".btw"
        ),
        key=lambda path: path.name.casefold(),
    )
    if not candidates:
        return MatchResult(None, [], f"产品合格证目录中没有顶层 BarTender 文件：{product_directory}")
    color_key = normalize_identity(color)
    if not color_key:
        return MatchResult(None, candidates, "产品信息 Excel 缺少可识别的代表颜色")
    colored = [path for path in candidates if color_key in normalize_identity(path.stem)]
    if not colored:
        return MatchResult(None, candidates, f"没有找到代表颜色 {color} 的 BarTender 文件")
    candidates = colored
    sized = [(path, extract_size(path.stem)) for path in candidates]
    valid = [(path, size) for path, size in sized if size is not None]
    if not valid:
        if len(candidates) == 1:
            logger.warning(
                "BarTender 唯一颜色候选未识别到数字尺码，按唯一候选选择 path=%r",
                str(candidates[0]),
            )
            return MatchResult(candidates[0], candidates, "代表颜色只有一个候选，使用唯一文件")
        return MatchResult(None, candidates, "BarTender 候选中没有可识别尺码")
    target_size = preferred_size if any(size == preferred_size for _, size in valid) else min(
        size for _, size in valid
    )
    target = [path for path, size in valid if size == target_size]
    if len(target) == 1:
        reason = f"选择优先尺码 {target_size}" if target_size == preferred_size else f"选择最小尺码 {target_size}"
        logger.info("BarTender 文件匹配完成 path=%r reason=%s", str(target[0]), reason)
        return MatchResult(target[0], candidates, reason)
    return MatchResult(None, target, f"代表颜色 {color} 的尺码 {target_size} 存在多个候选")
