"""骨架辅助标注的数据结构。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class PoseKeypoint:
    """单个人体关键点。

    参数:
        index: 关键点序号。
        name: 关键点名称。
        x: 源图像素 x 坐标。
        y: 源图像素 y 坐标。
        score: 关键点置信度。
    返回值:
        数据类实例。
    """

    index: int
    name: str
    x: float
    y: float
    score: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """转换为可写入 JSON 的字典。

        返回值:
            关键点字典。
        """
        return {
            "index": self.index,
            "name": self.name,
            "x": round(self.x, 2),
            "y": round(self.y, 2),
            "score": round(self.score, 4) if self.score is not None else None,
        }


@dataclass
class PosePerson:
    """单个人体骨架检测结果。

    参数:
        person_id: 人体编号。
        person_box: 人体检测框。
        keypoints: 关键点列表。
    返回值:
        数据类实例。
    """

    person_id: int
    person_box: list[int]
    keypoints: list[PoseKeypoint]

    def to_dict(self) -> dict[str, Any]:
        """转换为可写入 JSON 的字典。

        返回值:
            人体骨架字典。
        """
        return {
            "id": self.person_id,
            "person_box": self.person_box,
            "keypoints": [point.to_dict() for point in self.keypoints],
        }

