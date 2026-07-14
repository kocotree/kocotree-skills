"""review 阶段：从 summary 中汇总需要复查的失败项。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from core.output_layout import layout_from_annotations, load_summary, update_summary
from core.utils import get_logger

logger = get_logger(__name__)


def build_review_report(annotations_path: Path, output_path: Path | None = None) -> dict[str, Any]:
    """根据 summary.json 生成复查摘要。

    参数:
        annotations_path: 批次 annotations.json 路径。
        output_path: 兼容参数；当前输出结构固定，不单独写复查文件。
    返回值:
        复查摘要。
    """
    if not annotations_path.exists():
        raise FileNotFoundError(f"未找到标注清单: {annotations_path}")
    layout = layout_from_annotations(annotations_path)
    summary = load_summary(layout)
    render_products = summary.get("stages", {}).get("render", {}).get("items", [])
    review_items: list[dict[str, Any]] = []
    for product in render_products:
        for item in product.get("items", []):
            failures = item.get("failures", [])
            if not failures:
                continue
            review_items.append(
                {
                    "product": product.get("product"),
                    "color": item.get("color"),
                    "status": item.get("status"),
                    "failures": failures,
                    "annotated": item.get("skeleton", ""),
                    "crop": item.get("crop", ""),
                    "suggested_action": _suggest_action(failures),
                }
            )

    payload = {
        "items": review_items,
        "summary": {
            "review_items": len(review_items),
            "failed": sum(1 for item in review_items if item["status"] == "fail"),
        },
    }
    update_summary(layout, "review", payload)
    logger.info("复查摘要生成完成：%s", payload["summary"])
    return payload


def _suggest_action(failures: list[str]) -> str:
    """根据失败内容给出修正方向。"""
    text = "；".join(failures)
    if "缺少视觉标注" in text or "annotation" in text:
        return "补全 annotations.json 中的 crop_box 后重新校验。"
    subject_clipped = "head_box" in text or "garment_box" in text or "body_box" in text
    if "下边界" in text and subject_clipped:
        return "把下边界调整到目标区间，并移动或放大 crop_box 以完整保留人物和服装主体。"
    if "下边界" in text:
        return "把 crop_box 下边界调整到髋点至 garment_box 下限区间约 60% 的位置。"
    if subject_clipped:
        return "移动或放大 crop_box，完整保留头部、服装主体和视觉头顶。"
    if "crop_box" in text:
        return "调整 crop_box，让裁切框为方形，并与源图保持重叠区域。"
    if "商品图" in text or "颜色名" in text:
        return "检查透明商品图、颜色名匹配和模板贴片区域。"
    return "查看 crops 图片，修正 crop_box 后重新 render。"
