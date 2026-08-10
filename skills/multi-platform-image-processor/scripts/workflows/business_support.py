from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from common.product_info_reader import ProductInfoRecord


def default_business_report_path(product_code: str) -> Path:
    """生成完整处理流程的默认报告路径。"""
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_code = "".join(character for character in product_code if character.isalnum()) or "product"
    return Path(__file__).resolve().parents[1] / "output" / "report" / f"{safe_code}-{timestamp}-report.json"


def parse_box(value: str, label: str) -> tuple[int, int, int, int]:
    """解析逗号分隔的四整数矩形。"""
    try:
        numbers = tuple(int(part.strip()) for part in value.split(","))
    except ValueError as exc:
        raise RuntimeError(f"{label}必须是四个逗号分隔整数") from exc
    if len(numbers) != 4:
        raise RuntimeError(f"{label}必须是 left,top,right,bottom")
    left, top, right, bottom = numbers
    if left >= right or top >= bottom:
        raise RuntimeError(f"{label}的右下坐标必须大于左上坐标")
    return numbers


def record_to_dict(record: ProductInfoRecord) -> dict[str, Any]:
    """将产品信息记录转换为可写入 JSON 的对象。"""
    return {
        "文件": str(record.file),
        "工作表": record.sheet,
        "行号": record.row,
        "字段": {key: str(value) for key, value in record.data.items()},
    }


def product_match_to_dict(
    selected: ProductInfoRecord | None,
    candidates: list[object],
    reason: str,
) -> dict[str, Any]:
    """构造包含选中记录与全部候选的产品匹配报告。"""
    return {
        "匹配结论": reason,
        "选中记录": record_to_dict(selected) if selected else {},
        "候选记录": [
            record_to_dict(candidate)
            for candidate in candidates
            if isinstance(candidate, ProductInfoRecord)
        ],
    }


def load_plan(path: Path) -> dict[str, Any]:
    """读取 Agent 生成的视觉定位计划。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"视觉定位计划无法读取：{path}，{exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError("视觉定位计划根节点必须是对象")
    return data


def resolve_relative_image(root: Path, value: str) -> Path:
    """在工作根目录内解析视觉计划图片路径。"""
    raw = Path(value)
    if raw.is_absolute():
        raise RuntimeError("视觉定位计划中的图片必须使用相对路径")
    target = (root / raw).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise RuntimeError(f"视觉定位计划路径超出工作目录：{value}") from exc
    return target
