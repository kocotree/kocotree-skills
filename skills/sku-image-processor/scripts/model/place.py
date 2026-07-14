"""模特图放置：按 agent 标注的保留区域裁切并放到画布。

agent 负责主观构图（选 crop_box）；脚本负责确定性处理
（裁切、越界补背景、缩放）。背景来源由 prepare_image 按类别确定：
opaque 用模特图自带背景，transparent 用同级场景图。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image

from core.config import WorkflowConfig
from core.utils import get_logger
from model.common import crop_without_extension, prepare_image
from model.fill_model import fill_gaps_with_model
from qa.preview import draw_crop_box

logger = get_logger(__name__)


class FillModelRetryableError(RuntimeError):
    """生成模型补背景失败，可在批次末尾重试。"""


def _normalize_crop_box(crop_box: list[Any] | tuple[Any, ...]) -> tuple[int, int, int, int]:
    """把标注坐标转换为整数像素框。"""
    x1, y1, x2, y2 = crop_box
    return (
        int(round(float(x1))),
        int(round(float(y1))),
        int(round(float(x2))),
        int(round(float(y2))),
    )


def _is_crop_box_in_bounds(crop_box: tuple[int, int, int, int], image: Image.Image) -> bool:
    """判断裁切框是否不需要补背景。"""
    x1, y1, x2, y2 = crop_box
    width, height = image.size
    return x1 >= 0 and y1 >= 0 and x2 <= width and y2 <= height


def place_from_annotation(
    source_path: Path, bg_class: str, annotation: dict[str, Any],
    cfg: WorkflowConfig, qa_dir: Path | None = None, crop_output_path: Path | None = None,
    skeleton_path: Path | None = None, fill_input_path: Path | None = None,
    fill_result_path: Path | None = None,
) -> tuple[Image.Image, dict[str, Any]]:
    """按 agent 标注裁切模特图并放到画布。

    流程：按 bg_class 取参考底图（尺寸不变）→ 按 crop_box 裁切或补背景 → 缩放到画布。

    参数:
        source_path: 模特图路径。
        bg_class: "opaque"（自带背景）或 "transparent"（用同级场景图作背景）。
        annotation: 该颜色的视觉标注（仅含 crop_box）。
        cfg: 工作流配置。
        qa_dir: 批次输出目录；兼容参数，用于缺省生图调试图目录。
        crop_output_path: 裁切检查图输出路径，可为空。
        skeleton_path: 骨架标注图路径；存在时在图上叠加红色裁切框。
        fill_input_path: 生图补齐输入图输出路径，可为空。
        fill_result_path: 生图补齐结果图输出路径，可为空。
    返回:
        (画布, 布局信息)。
    """
    image = prepare_image(source_path, bg_class, cfg)
    size = cfg.canvas_size
    crop_box = _normalize_crop_box(annotation["crop_box"])
    if skeleton_path is not None:
        skeleton_path.parent.mkdir(parents=True, exist_ok=True)
        if skeleton_path.exists():
            with Image.open(skeleton_path) as skeleton_image:
                annotation_image = skeleton_image.convert("RGB")
        else:
            logger.warning("未找到骨架标注图，使用模特底图绘制裁切框: %s", skeleton_path)
            annotation_image = image
        draw_crop_box(annotation_image, crop_box).save(skeleton_path, quality=95)
        logger.info("已在骨架标注图叠加 crop_box: %s", skeleton_path)

    if _is_crop_box_in_bounds(crop_box, image):
        crop = crop_without_extension(image, crop_box)
        fill_model_used = False
        background_extended = False
        decision = f"{bg_class}：按 crop_box 裁切"
    else:
        output_dir = fill_input_path.parent if fill_input_path is not None else qa_dir
        if output_dir is None:
            output_dir = Path.cwd()
        logger.info("crop_box 越界，调用生成模型补背景: %s source=%dx%d", crop_box, image.width, image.height)
        crop = fill_gaps_with_model(
            image,
            crop_box,
            output_dir,
            fill_input_path=fill_input_path,
            fill_result_path=fill_result_path,
        )
        if crop is None:
            raise FillModelRetryableError("crop_box 越界补背景失败，请确认授权和生成模型服务可用")
        fill_model_used = True
        background_extended = True
        decision = f"{bg_class}：crop_box 越界，生成模型补背景后裁切"

    if crop_output_path is not None:
        crop_output_path.parent.mkdir(parents=True, exist_ok=True)
        crop.convert("RGB").save(crop_output_path, quality=92)

    canvas = crop.resize((size, size), Image.Resampling.LANCZOS).convert("RGBA")
    logger.info("模特图放置完成: %s [%s]", source_path.name, bg_class)
    layout = {
        "mode": "model",
        "bg_class": bg_class,
        "source_size": list(image.size),
        "crop_box": list(crop_box),
        "background_extended": background_extended,
        "fill_model_used": fill_model_used,
        "skeleton": str(skeleton_path) if skeleton_path else "",
        "fill_input": str(fill_input_path) if fill_model_used and fill_input_path else "",
        "fill_result": str(fill_result_path) if fill_model_used and fill_result_path else "",
        "decision": decision,
        "annotation_quality": "agent_annotated",
        "boxes": {},
    }
    return canvas, layout
