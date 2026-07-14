"""根据 YOLO 骨架结果生成当前项目可参考的 annotation 草稿。"""
from __future__ import annotations

from typing import Any

from pose.schema import PoseKeypoint

COCO17_NAMES = [
    "nose",
    "left_eye",
    "right_eye",
    "left_ear",
    "right_ear",
    "left_shoulder",
    "right_shoulder",
    "left_elbow",
    "right_elbow",
    "left_wrist",
    "right_wrist",
    "left_hip",
    "right_hip",
    "left_knee",
    "right_knee",
    "left_ankle",
    "right_ankle",
]

COCO17_EDGES = [
    [0, 1],
    [0, 2],
    [1, 3],
    [2, 4],
    [5, 6],
    [5, 7],
    [7, 9],
    [6, 8],
    [8, 10],
    [5, 11],
    [6, 12],
    [11, 12],
    [11, 13],
    [13, 15],
    [12, 14],
    [14, 16],
]


def point_is_valid(point: PoseKeypoint, threshold: float = 0.2) -> bool:
    """判断关键点是否可用于推导框。

    参数:
        point: 单个关键点。
        threshold: 置信度阈值。
    返回值:
        可用返回 True。
    """
    return point.score is None or point.score >= threshold


def box_from_points(points: list[PoseKeypoint], names: set[str], image_size: tuple[int, int], margin_ratio: float) -> list[int]:
    """根据指定关键点生成外接框。

    参数:
        points: 关键点列表。
        names: 参与计算的关键点名称集合。
        image_size: 图片尺寸。
        margin_ratio: 外扩比例。
    返回值:
        [x1, y1, x2, y2]；无可用点时返回空数组。
    """
    width, height = image_size
    selected = [point for point in points if point.name in names and point_is_valid(point)]
    if not selected:
        return []
    xs = [point.x for point in selected]
    ys = [point.y for point in selected]
    x1, x2 = min(xs), max(xs)
    y1, y2 = min(ys), max(ys)
    box_width = max(12.0, x2 - x1)
    box_height = max(12.0, y2 - y1)
    return [
        max(0, min(width, round(x1 - box_width * margin_ratio))),
        max(0, min(height, round(y1 - box_height * margin_ratio))),
        max(0, min(width, round(x2 + box_width * margin_ratio))),
        max(0, min(height, round(y2 + box_height * margin_ratio))),
    ]


def classify_pose_type(points: list[PoseKeypoint], body_box: list[int]) -> str:
    """根据关键点粗略推导 pose_type。

    参数:
        points: 关键点列表。
        body_box: 人体外接框。
    返回值:
        当前项目可用的 pose_type 字符串。
    """
    valid_names = {point.name for point in points if point_is_valid(point, 0.25)}
    has_ankle = bool({"left_ankle", "right_ankle"} & valid_names)
    has_knee = bool({"left_knee", "right_knee"} & valid_names)
    if not body_box:
        return ""
    box_width = body_box[2] - body_box[0]
    box_height = body_box[3] - body_box[1]
    if box_height <= 0:
        return ""
    if box_width / box_height > 0.72:
        return "jumping_action"
    if has_ankle and has_knee:
        return "full_body"
    if has_knee:
        return "walking_midshot"
    return "standing_half_body"


def _point_by_name(points: list[PoseKeypoint], name: str, threshold: float = 0.2) -> PoseKeypoint | None:
    """按名称取一个可用关键点。"""
    for point in points:
        if point.name == name and point_is_valid(point, threshold):
            return point
    return None


def _point_to_dict(point: PoseKeypoint | None) -> dict[str, float] | None:
    """把关键点转成可写入 summary 的坐标字典。"""
    if point is None:
        return None
    payload = {"x": round(point.x, 2), "y": round(point.y, 2)}
    if point.score is not None:
        payload["score"] = round(point.score, 4)
    return payload


def build_crop_guides(points: list[PoseKeypoint], body_box: list[int], image_size: tuple[int, int]) -> dict[str, Any]:
    """生成 crop_box 标注时使用的骨架参照点。

    参数:
        points: YOLO 输出的关键点列表。
        body_box: 人体检测框，包含帽子、头发等视觉头部范围。
        image_size: 图片尺寸。
    返回值:
        crop_box 构图参照信息。
    """
    left_hip = _point_by_name(points, "left_hip")
    right_hip = _point_by_name(points, "right_hip")
    hip_points = [point for point in [left_hip, right_hip] if point is not None]
    hip_anchor_y = round(max(point.y for point in hip_points), 2) if hip_points else None
    return {
        "image_size": list(image_size),
        "body_box": body_box,
        "body_top_y": body_box[1] if body_box else None,
        "left_hip": _point_to_dict(left_hip),
        "right_hip": _point_to_dict(right_hip),
        "hip_anchor_y": hip_anchor_y,
        "target_top_margin_final_px": 120,
        "top_rule": "crop_y1 = body_box.top - crop_side * 120 / 1440",
        "bottom_rule": "crop_y2 以 hip_anchor_y 到 garment_box.bottom 区间的 60% 为目标，允许 55%-75%",
    }


def build_annotation_draft(points: list[PoseKeypoint], person_box: list[int], image_size: tuple[int, int]) -> dict[str, Any]:
    """把骨架结果转换成 annotation 草稿。

    参数:
        points: 关键点列表。
        person_box: YOLO 检测到的人体框。
        image_size: 图片尺寸。
    返回值:
        当前项目 annotation 草稿。
    """
    all_names = {point.name for point in points}
    body_box = person_box or box_from_points(points, all_names, image_size, 0.12)
    head_names = {"nose", "left_eye", "right_eye", "left_ear", "right_ear"}
    garment_names = {"left_shoulder", "right_shoulder", "left_hip", "right_hip"}
    return {
        "face_box": box_from_points(points, head_names, image_size, 0.35),
        "head_box": box_from_points(points, head_names, image_size, 0.55),
        "garment_box": box_from_points(points, garment_names, image_size, 0.45),
        "body_box": body_box,
        "crop_guides": build_crop_guides(points, body_box, image_size),
        "pose_type": classify_pose_type(points, body_box),
        "notes": "YOLO 骨架辅助草稿，仅用于视觉模型或 agent 标注参考。",
    }
