"""prep 内部使用的 YOLO 骨架辅助材料生成。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image

from core.annotations import load_annotations
from core.config import WorkflowConfig, load_config
from core.output_layout import OutputLayout
from core.utils import get_logger
from model.common import prepare_image
from pose.annotation import build_annotation_draft
from pose.detector import load_yolo_pose_model, run_yolo_pose_with_model
from pose.schema import PosePerson
from pose.visualize import draw_pose_result

logger = get_logger(__name__)


def _build_item_result(
    image: Image.Image,
    people: list[PosePerson],
    source_image: Path,
    product: str,
    color: str,
    output_path: Path,
) -> dict[str, Any]:
    """生成单个颜色的骨架辅助产物。

    参数:
        image: 骨架检测参考图。
        people: YOLO 检测到的人体列表。
        source_image: 原始模特图路径。
        product: 商品名。
        color: 颜色名。
        output_path: 骨架画框图输出路径。
    返回值:
        单色处理摘要。
    """
    image_size = image.size
    drafts = [build_annotation_draft(person.keypoints, person.person_box, image_size) for person in people]
    draw_pose_result(image, people, drafts, output_path)
    logger.info("%s/%s 骨架辅助完成：%d 人", product, color, len(people))
    return {
        "product": product,
        "color": color,
        "source_image": str(source_image),
        "people": len(people),
        "image": str(output_path),
        "draft": drafts[0] if drafts else {},
    }


def run_pose_assist(
    annotations_path: Path,
    annotated_root: Path | None = None,
    model_name: str = "models/yolo11n-pose.pt",
    confidence: float = 0.25,
) -> dict[str, Any]:
    """生成 YOLO 骨架辅助材料。

    参数:
        annotations_path: prep 生成的 annotations.json 路径。
        annotated_root: 标注图片输出目录；为空时使用批次 annotated/。
        model_name: YOLO pose 权重名或本地路径。
        confidence: 检测置信度阈值。
    返回值:
        骨架辅助汇总报告。
    """
    if not annotations_path.exists():
        raise FileNotFoundError(f"未找到标注清单: {annotations_path}")
    annotations = load_annotations(annotations_path)
    template_path = Path(annotations.get("template", ""))
    if template_path.exists():
        cfg = load_config(template_path)
    else:
        logger.warning("annotations 中的模板路径不可用，骨架辅助流程使用默认配置: %s", template_path)
        cfg = WorkflowConfig()
    layout = OutputLayout(annotations_path.parent)
    output_root = annotated_root or layout.annotated_dir
    output_root.mkdir(parents=True, exist_ok=True)

    report: dict[str, Any] = {
        "annotations": str(annotations_path),
        "output_root": str(output_root),
        "model": model_name,
        "confidence": confidence,
        "items": [],
    }
    model = load_yolo_pose_model(model_name)
    for product, colors in annotations.get("products", {}).items():
        for color, info in colors.items():
            source = info.get("source_image")
            if not source:
                logger.info("%s/%s 无模特图，跳过骨架辅助", product, color)
                continue
            source_path = Path(source)
            output_path = layout.skeleton_path(product, color)
            image = prepare_image(source_path, info.get("bg_class", "opaque"), cfg)
            people = run_yolo_pose_with_model(image=image, model=model, confidence=confidence)
            report["items"].append(_build_item_result(image, people, source_path, product, color, output_path))

    report["summary"] = {
        "items": len(report["items"]),
        "people": sum(item["people"] for item in report["items"]),
    }
    logger.info("骨架辅助流程完成：%s", report["summary"])
    return report
