"""YOLO Pose 检测封装。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from core.utils import get_logger
from pose.annotation import COCO17_NAMES
from pose.schema import PoseKeypoint, PosePerson

logger = get_logger(__name__)


def load_yolo_pose_model(model_name: str) -> Any:
    """加载 YOLO Pose 模型。

    参数:
        model_name: YOLO pose 权重名或本地路径。
    返回值:
        Ultralytics YOLO 模型实例。
    """
    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise RuntimeError(
            "缺少 ultralytics。请先在 scripts 目录运行：uv sync --python 3.12"
        ) from exc
    logger.info("加载 YOLO Pose 模型: %s", model_name)
    return YOLO(model_name)


def run_yolo_pose_with_model(image: Image.Image, model: Any, confidence: float) -> list[PosePerson]:
    """使用已加载模型对单张图片运行 YOLO Pose。

    参数:
        image: 输入图片。
        model: 已加载的 Ultralytics YOLO 模型。
        confidence: 检测置信度阈值。
    返回值:
        人体骨架检测结果列表。
    """
    rgb = image.convert("RGB")
    result = model(np.array(rgb), conf=confidence, verbose=False)[0]
    boxes = result.boxes.xyxy.cpu().numpy().tolist() if result.boxes is not None else []
    keypoints_xy = result.keypoints.xy.cpu().numpy().tolist() if result.keypoints is not None else []
    keypoints_conf = (
        result.keypoints.conf.cpu().numpy().tolist()
        if result.keypoints is not None and result.keypoints.conf is not None
        else []
    )

    people: list[PosePerson] = []
    for person_index, xy_values in enumerate(keypoints_xy):
        points: list[PoseKeypoint] = []
        for point_index, coords in enumerate(xy_values):
            score = keypoints_conf[person_index][point_index] if person_index < len(keypoints_conf) else None
            points.append(
                PoseKeypoint(
                    index=point_index,
                    name=COCO17_NAMES[point_index],
                    x=float(coords[0]),
                    y=float(coords[1]),
                    score=float(score) if score is not None else None,
                )
            )
        person_box = [round(value) for value in boxes[person_index]] if person_index < len(boxes) else []
        people.append(PosePerson(person_id=person_index + 1, person_box=person_box, keypoints=points))
    logger.info("YOLO Pose 检测到 %d 个人体", len(people))
    return people


def run_yolo_pose(image: Image.Image, model_name: str, confidence: float) -> list[PosePerson]:
    """加载模型并对单张图片运行 YOLO Pose。

    参数:
        image: 输入图片。
        model_name: YOLO pose 权重名或本地路径。
        confidence: 检测置信度阈值。
    返回值:
        人体骨架检测结果列表。
    """
    model = load_yolo_pose_model(model_name)
    return run_yolo_pose_with_model(image=image, model=model, confidence=confidence)


def save_pose_input(image: Image.Image, output_path: Path) -> None:
    """保存骨架检测实际输入图。

    参数:
        image: 输入图片。
        output_path: 保存路径。
    返回值:
        无。
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(output_path, quality=92)
