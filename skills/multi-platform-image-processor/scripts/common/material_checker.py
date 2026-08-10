from __future__ import annotations

import re
from dataclasses import dataclass


IGNORED_LABELS = ("中文面料信息", "面料成分", "面料", "材质", "成分")


@dataclass(frozen=True)
class MaterialCheck:
    """保存一处详情页面料的核对结果。"""

    expected: str
    actual: str
    normalized_expected: str
    normalized_actual: str
    matches: bool


def normalize_material_text(value: str) -> str:
    """归一化面料提示词、空白和非实质分隔符。"""
    text = str(value).casefold()
    for label in IGNORED_LABELS:
        text = text.replace(label.casefold(), "")
    text = re.sub(r"[\s+＋、，,；;：:/／]+", "", text)
    return text


def compare_material(expected: str, actual: str) -> MaterialCheck:
    """比较 Excel 中文面料与详情页识别文本。

    参数：
        expected：Excel 中文面料原文。
        actual：详情页识别文本。
    返回值：
        包含原文、归一化值和一致性结论的结果。
    """
    normalized_expected = normalize_material_text(expected)
    normalized_actual = normalize_material_text(actual)
    return MaterialCheck(
        expected,
        actual,
        normalized_expected,
        normalized_actual,
        bool(normalized_expected) and normalized_expected == normalized_actual,
    )
