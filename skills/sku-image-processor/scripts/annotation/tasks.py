"""annotate 阶段：汇总 agent/视觉模型标注任务。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from core.annotations import load_annotations
from core.output_layout import layout_from_annotations, load_summary, update_summary
from core.utils import get_logger

logger = get_logger(__name__)

CROP_BOX_RULES = [
    "最终画布中 body_box 顶部距离顶部约 120px，帽子、头发和耳机都按 body_box 计算。",
    "crop_box 下边界以 hip_anchor_y 到 garment_box 下限区间的 60% 位置为目标，必须落在 55%-75% 范围内。",
    "garment_box 只用于确定裁切下边界的最下限，不能直接作为 crop_box。",
    "crop_box 必须完整包含 head_box，并在横向完整包含 garment_box，不能裁断头部或服装主体。",
    "人物保持在左侧展示区的视觉中央。",
    "服装主体不能进入右侧 safe_patch_zone，不能被商品贴片或颜色标签明显遮挡；这是硬规则。",
    "右侧商品贴片和颜色标签必须完整展示。",
    "手持道具不作为保留目标，必要时可裁掉，优先展示穿着商品主体。",
    "当原图右侧空间不够时，不要为了留在源图内而让主体被遮挡；应把 crop_box 整体向右移动到源图外，触发生图补背景。",
    "宁愿调用生图补背景，也不要输出服装主体被右侧商品标签遮挡的 crop_box。",
    "crop_box 可以越界补背景，但最终背景必须自然、无明显接缝。",
]


def _pose_guides_by_item(summary: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    """从 summary 中提取每个颜色的骨架构图参照。"""
    items = summary.get("stages", {}).get("pose_assist", {}).get("items", [])
    guides: dict[tuple[str, str], dict[str, Any]] = {}
    for item in items:
        draft = item.get("draft") if isinstance(item, dict) else {}
        crop_guides = draft.get("crop_guides") if isinstance(draft, dict) else None
        if not crop_guides:
            continue
        guides[(item.get("product", ""), item.get("color", ""))] = crop_guides
    return guides


def _item_paths(batch_root: Path, product: str, color: str) -> dict[str, str]:
    """组装单色标注需要查看的辅助材料路径。

    参数:
        batch_root: 批次输出目录。
        product: 商品名。
        color: 颜色名。
    返回值:
        辅助材料路径字典。
    """
    return {
        "grid": str(batch_root / "annotated" / product / f"{color}_grid.jpg"),
        "skeleton": str(batch_root / "annotated" / product / f"{color}_skeleton.jpg"),
    }


def build_annotation_tasks(annotations_path: Path, output_dir: Path | None = None) -> dict[str, Any]:
    """生成标注任务摘要，供 agent 或视觉模型逐项填写 annotations.json。

    参数:
        annotations_path: prep 生成的 annotations.json 路径。
        output_dir: 兼容参数；当前输出结构固定，不单独写任务文件。
    返回值:
        标注任务摘要。
    """
    if not annotations_path.exists():
        raise FileNotFoundError(f"未找到标注清单: {annotations_path}")
    layout = layout_from_annotations(annotations_path)
    summary = load_summary(layout)
    pose_guides = _pose_guides_by_item(summary)
    annotations = load_annotations(annotations_path)
    tasks: list[dict[str, Any]] = []
    for product, colors in annotations.get("products", {}).items():
        for color, info in colors.items():
            if info.get("bg_class") == "no_model":
                continue
            tasks.append(
                {
                    "product": product,
                    "color": color,
                    "bg_class": info.get("bg_class"),
                    "source_image": info.get("source_image", ""),
                    "source_size": info.get("source_size", []),
                    "template_regions": str(layout.template_regions_path),
                    "materials": _item_paths(annotations_path.parent, product, color),
                    "required_annotation_fields": ["crop_box"],
                    "crop_box_rules": CROP_BOX_RULES,
                    "pose_crop_guides": pose_guides.get((product, color), {}),
                }
            )

    payload = {
        "annotations": str(annotations_path),
        "batch_root": str(annotations_path.parent),
        "task_count": len(tasks),
        "crop_box_rules": CROP_BOX_RULES,
        "tasks": tasks,
    }
    update_summary(layout, "annotate", {"task_count": len(tasks), "crop_box_rules": CROP_BOX_RULES, "tasks": tasks})
    logger.info("annotate 任务摘要生成完成：%d 项", len(tasks))
    return payload
