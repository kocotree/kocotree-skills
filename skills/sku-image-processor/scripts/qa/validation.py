"""最小验收：只判断脚本能确定的硬失败。

验收只读取结构化布局数据，不读取 PIL 画出来的检查图。
构图好坏、人物观感、道具取舍交给人工或视觉模型复查。
"""
from __future__ import annotations

from typing import Any

from core.config import WorkflowConfig
from core.utils import get_logger

logger = get_logger(__name__)


def validate_layout(layout: dict[str, Any], cfg: WorkflowConfig, output_kind: str) -> dict[str, list[str]]:
    """对单张合成图做最小硬校验。

    参数:
        layout: 合成布局信息，含 product_image、label 等结构化数据。
        cfg: 工作流配置，保留参数用于统一调用。
        output_kind: 输出类型，如 complete_sku_jpg / model_only_jpg / transparent_template_png。
    返回:
        {"failures": [...]}。
    """
    failures: list[str] = []

    if output_kind != "model_only_jpg":
        if not layout.get("product_image"):
            failures.append("缺少商品图放置")
        if not layout.get("label"):
            failures.append("缺少颜色名标签")

    return {"failures": failures}
