"""validate-annotation 阶段：校验 agent/视觉模型填写的标注清单。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from core.annotations import load_annotations
from core.config import WorkflowConfig, load_config
from core.output_layout import layout_from_annotations, load_summary, update_summary
from core.utils import get_logger

logger = get_logger(__name__)

CROP_BOTTOM_TARGET_RATIO = 0.60
CROP_BOTTOM_MIN_RATIO = 0.55
CROP_BOTTOM_MAX_RATIO = 0.75


def _is_box(value: Any) -> bool:
    """判断值是否为四元坐标框。"""
    return isinstance(value, list) and len(value) == 4 and all(isinstance(item, (int, float)) for item in value)


def _check_crop_box(value: Any, source_size: list[int]) -> list[str]:
    """校验 crop_box 的格式与可渲染性。

    参数:
        value: 字段值。
        source_size: 源图尺寸 [宽, 高]。
    返回值:
        错误列表。
    """
    if not _is_box(value):
        return ["crop_box 必须是四元坐标"]
    x1, y1, x2, y2 = value
    errors: list[str] = []
    if x2 <= x1 or y2 <= y1:
        errors.append("crop_box 坐标顺序错误")
    side_x = x2 - x1
    side_y = y2 - y1
    if abs(side_x - side_y) > 2:
        errors.append("crop_box 必须为方形")
    if source_size:
        width, height = source_size
        overlap_w = min(x2, width) - max(x1, 0)
        overlap_h = min(y2, height) - max(y1, 0)
        if overlap_w <= 0 or overlap_h <= 0:
            errors.append("crop_box 必须与源图有重叠区域")
    return errors


def _pose_drafts_by_item(summary: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    """从 summary 中按商品和颜色提取骨架草稿。"""
    items = summary.get("stages", {}).get("pose_assist", {}).get("items", [])
    drafts: dict[tuple[str, str], dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        draft = item.get("draft")
        if isinstance(draft, dict):
            drafts[(item.get("product", ""), item.get("color", ""))] = draft
    return drafts


def _map_box_to_canvas(box: list[int | float], crop_box: list[int | float], canvas_size: int) -> tuple[float, float, float, float]:
    """把源图坐标框映射到最终画布坐标。"""
    x1, y1, x2, y2 = crop_box
    side = x2 - x1
    bx1, by1, bx2, by2 = box
    return (
        (bx1 - x1) / side * canvas_size,
        (by1 - y1) / side * canvas_size,
        (bx2 - x1) / side * canvas_size,
        (by2 - y1) / side * canvas_size,
    )


def _intersects(box_a: tuple[float, float, float, float], box_b: tuple[int, int, int, int]) -> bool:
    """判断两个矩形是否相交。"""
    ax1, ay1, ax2, ay2 = box_a
    bx1, by1, bx2, by2 = box_b
    return min(ax2, bx2) > max(ax1, bx1) and min(ay2, by2) > max(ay1, by1)


def _check_safe_patch_overlap(annotation: dict[str, Any], draft: dict[str, Any], cfg: WorkflowConfig) -> list[str]:
    """校验服装参考框是否进入右侧贴片危险区。

    参数:
        annotation: 当前颜色的标注。
        draft: YOLO 骨架辅助草稿。
        cfg: 工作流配置。
    返回值:
        错误列表。
    """
    crop_box = annotation.get("crop_box") or []
    if not _is_box(crop_box):
        return []
    garment_box = draft.get("garment_box") or []
    if not _is_box(garment_box):
        return []
    mapped = _map_box_to_canvas(garment_box, crop_box, cfg.canvas_size)
    if not _intersects(mapped, cfg.layout.safe_patch_zone):
        return []
    return [
        "服装主体进入右侧商品贴片危险区：宁愿让 crop_box 越界调用生图补背景，也不能被商品标签遮挡"
    ]


def _check_crop_bottom_range(annotation: dict[str, Any], draft: dict[str, Any]) -> list[str]:
    """校验 crop_box 下边界是否位于下摆参考区间的合理位置。

    参数:
        annotation: 当前颜色的标注。
        draft: YOLO 骨架辅助草稿，包含 garment_box 和 crop_guides。
    返回值:
        错误列表；缺少骨架参考时不做该项硬校验。
    """
    crop_box = annotation.get("crop_box") or []
    if not _is_box(crop_box):
        return []
    garment_box = draft.get("garment_box") or []
    crop_guides = draft.get("crop_guides") or {}
    hip_anchor_y = crop_guides.get("hip_anchor_y") if isinstance(crop_guides, dict) else None
    if not _is_box(garment_box) or not isinstance(hip_anchor_y, (int, float)):
        return []

    range_top = float(hip_anchor_y)
    range_bottom = float(garment_box[3])
    crop_bottom = float(crop_box[3])
    if range_bottom + 2 < range_top:
        return ["骨架辅助坐标异常：garment_box 下限位于髋点上方"]
    interval = range_bottom - range_top
    allowed_top = range_top + interval * CROP_BOTTOM_MIN_RATIO
    allowed_bottom = range_top + interval * CROP_BOTTOM_MAX_RATIO
    if crop_bottom + 2 >= allowed_top and crop_bottom - 2 <= allowed_bottom:
        return []
    return [
        "crop_box 下边界必须位于髋点至 garment_box 下限区间的 "
        f"{CROP_BOTTOM_MIN_RATIO:.0%}-{CROP_BOTTOM_MAX_RATIO:.0%}，"
        f"目标位置为 {CROP_BOTTOM_TARGET_RATIO:.0%}"
    ]


def _check_subject_containment(annotation: dict[str, Any], draft: dict[str, Any]) -> list[str]:
    """校验裁切框是否完整保留头部和服装主体。

    参数:
        annotation: 当前颜色的标注。
        draft: YOLO 骨架辅助草稿，包含 head_box、garment_box 和 body_box。
    返回值:
        人物关键区域被裁断时的错误列表。
    """
    crop_box = annotation.get("crop_box") or []
    if not _is_box(crop_box):
        return []
    crop_x1, crop_y1, crop_x2, _ = [float(value) for value in crop_box]
    errors: list[str] = []
    head_box = draft.get("head_box") or []
    garment_box = draft.get("garment_box") or []
    body_box = draft.get("body_box") or []

    if _is_box(head_box):
        head_x1, head_y1, head_x2, head_y2 = [float(value) for value in head_box]
        if crop_x1 > head_x1 + 2 or crop_x2 < head_x2 - 2 or crop_y1 > head_y1 + 2:
            errors.append("crop_box 裁断 head_box，必须完整保留人物头部")
        if float(crop_box[3]) < head_y2 - 2:
            errors.append("crop_box 下边界裁断 head_box")
    if _is_box(garment_box):
        garment_x1, _, garment_x2, _ = [float(value) for value in garment_box]
        if crop_x1 > garment_x1 + 2 or crop_x2 < garment_x2 - 2:
            errors.append("crop_box 横向裁断 garment_box，必须完整保留服装主体")
    if _is_box(body_box) and crop_y1 > float(body_box[1]) + 2:
        errors.append("crop_box 上边界裁断 body_box.top，必须完整保留视觉头部")
    return errors


def _validate_one_annotation(
    product: str,
    color: str,
    info: dict[str, Any],
    pose_drafts: dict[tuple[str, str], dict[str, Any]],
    cfg: WorkflowConfig,
) -> dict[str, Any]:
    """校验单个颜色的 annotation 字段。

    参数:
        product: 商品名。
        color: 颜色名。
        info: annotations.json 中的单色条目。
        pose_drafts: 按商品和颜色索引的骨架辅助草稿。
        cfg: 工作流配置，用于读取画布和贴片区域。
    返回值:
        单色校验结果。
    """
    result: dict[str, Any] = {"product": product, "color": color, "status": "pass", "failures": []}
    if info.get("bg_class") == "no_model":
        result["status"] = "skip"
        return result

    annotation = info.get("annotation")
    source_size = info.get("source_size") or []
    if not isinstance(annotation, dict):
        result["failures"].append("缺少 annotation 对象")
        result["status"] = "fail"
        return result

    crop_box = annotation.get("crop_box", [])
    if not crop_box:
        result["failures"].append("crop_box 必填")
    else:
        result["failures"].extend(_check_crop_box(crop_box, source_size))
        draft = pose_drafts.get((product, color), {})
        result["failures"].extend(_check_safe_patch_overlap(annotation, draft, cfg))
        result["failures"].extend(_check_crop_bottom_range(annotation, draft))
        result["failures"].extend(_check_subject_containment(annotation, draft))

    if result["failures"]:
        result["status"] = "fail"
    return result


def validate_annotations(annotations_path: Path, output_path: Path | None = None) -> dict[str, Any]:
    """校验完整 annotations.json 并更新 summary.json。

    参数:
        annotations_path: 待校验的标注清单路径。
        output_path: 兼容参数；当前输出结构固定，不单独写校验文件。
    返回值:
        校验报告。
    """
    if not annotations_path.exists():
        raise FileNotFoundError(f"未找到标注清单: {annotations_path}")
    annotations = load_annotations(annotations_path)
    layout = layout_from_annotations(annotations_path)
    summary = load_summary(layout)
    pose_drafts = _pose_drafts_by_item(summary)
    template_path = Path(annotations.get("template", ""))
    cfg = load_config(template_path) if template_path.exists() else WorkflowConfig()

    items: list[dict[str, Any]] = []
    for product, colors in annotations.get("products", {}).items():
        for color, info in colors.items():
            result = _validate_one_annotation(product, color, info, pose_drafts, cfg)
            items.append(result)
            if result["status"] == "fail":
                logger.warning("%s/%s 标注验收失败: %s", product, color, result["failures"])
            else:
                logger.info("%s/%s 标注验收结果: %s", product, color, result["status"])

    report = {
        "annotations": str(annotations_path),
        "items": items,
        "summary": {
            "items": len(items),
            "passed": sum(1 for item in items if item["status"] == "pass"),
            "failed": sum(1 for item in items if item["status"] == "fail"),
            "skipped": sum(1 for item in items if item["status"] == "skip"),
        },
    }
    update_summary(layout, "validate_annotation", report)
    logger.info("标注校验完成：%s", report["summary"])
    return report
