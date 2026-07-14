"""prep 阶段：扫描素材、判定背景类别、生成标注清单骨架、坐标网格和 YOLO 骨架图。

产物供运行 skill 的 agent 或视觉模型填写视觉标注，随后交给 validate-annotation 与 render 阶段。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image

from core.annotations import build_skeleton
from core.config import load_config
from core.output_layout import OutputLayout, update_summary
from core.utils import clear_directory, get_logger, write_json
from model.common import prepare_image
from qa.grid import draw_coordinate_grid
from pose.pipeline import run_pose_assist
from template.template import get_clean_template, get_template_regions

logger = get_logger(__name__)


def run_prep(
    input_root: Path,
    batch_root: Path,
    template_path: Path,
    pose_model_name: str = "models/yolo11n-pose.pt",
    pose_confidence: float = 0.25,
    skip_pose: bool = False,
) -> dict[str, Any]:
    """生成标注清单骨架、坐标网格参照图和 YOLO 骨架辅助材料。

    参数:
        input_root: 素材根目录，下含若干商品目录（模特图/、透明图/）。
        batch_root: 批次输出根目录。
        template_path: 模板图片路径（用于加载画布尺寸/配置并写入清单）。
        pose_model_name: YOLO pose 权重名或本地权重路径。
        pose_confidence: YOLO 人体检测置信度阈值。
        skip_pose: 是否跳过骨架辅助材料生成。
    返回:
        生成的标注清单字典。
    """
    if not input_root.exists():
        raise FileNotFoundError(f"素材根目录不存在: {input_root}")
    if not template_path.exists():
        raise FileNotFoundError(f"未找到模板: {template_path}")

    cfg = load_config(template_path)
    # 预热模板缓存（clean_template / 参考线图），并据此确定画布尺寸
    clean_template, _ = get_clean_template(template_path, cfg)
    cfg.canvas_size = clean_template.width
    template_regions = get_template_regions(template_path, clean_template, cfg)

    layout = OutputLayout(batch_root)
    if batch_root.exists():
        clear_directory(batch_root)
    batch_root.mkdir(parents=True, exist_ok=True)

    # 模板参考图属于标注图片，确保模型标注 crop_box 前先核对右侧商品贴片和绿色标签版式。
    layout.template_regions_path.parent.mkdir(parents=True, exist_ok=True)
    template_regions.save(layout.template_regions_path, quality=95)

    skeleton = build_skeleton(input_root, template_path, cfg)

    # 为每张模特图生成坐标网格参照图，帮 agent 给准源图像素坐标
    grid_count = 0
    for product, colors in skeleton["products"].items():
        for color, info in colors.items():
            if not info.get("source_image"):
                continue  # 只有透明商品图、无模特图，跳过
            source = Path(info["source_image"])
            # 网格底图用 prepare_image：透明模特显示在场景图上，坐标与 render 裁切一致
            try:
                base = prepare_image(source, info["bg_class"], cfg)
            except FileNotFoundError as exc:
                logger.warning("%s，网格图退回用原图", exc)
                base = Image.open(source)
            grid = draw_coordinate_grid(base)
            out_path = layout.grid_path(product, color)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            grid.save(out_path, quality=85)
            grid_count += 1

    annotations_path = layout.annotations_path
    write_json(annotations_path, skeleton)
    if skip_pose:
        logger.info("按参数跳过 YOLO 骨架辅助材料生成")
        pose_report = {"items": 0, "people": 0, "skipped": True}
    else:
        pose_report = run_pose_assist(
            annotations_path=annotations_path,
            annotated_root=layout.annotated_dir,
            model_name=pose_model_name,
            confidence=pose_confidence,
        )
        update_summary(layout, "pose_assist", pose_report)
    update_summary(
        layout,
        "prep",
        {
            "input_root": str(input_root),
            "template": str(template_path),
            "annotations": str(annotations_path),
            "template_regions": str(layout.template_regions_path),
            "grid_images": grid_count,
            "pose": pose_report.get("summary", pose_report),
        },
    )
    logger.info("prep 完成：标注清单 %s，待标注模特图 %d 张", annotations_path, grid_count)
    return skeleton
