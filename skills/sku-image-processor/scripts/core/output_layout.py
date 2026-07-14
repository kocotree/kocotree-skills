"""统一管理脚本输出结构。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.utils import read_json, write_json


@dataclass(frozen=True)
class OutputLayout:
    """单个批次的固定输出路径。

    参数:
        batch_root: 批次输出根目录。
    返回值:
        输出路径布局实例。
    """

    batch_root: Path

    @property
    def annotations_path(self) -> Path:
        """返回标注清单路径。"""
        return self.batch_root / "annotations.json"

    @property
    def summary_path(self) -> Path:
        """返回汇总文件路径。"""
        return self.batch_root / "summary.json"

    @property
    def final_dir(self) -> Path:
        """返回最终交付图目录。"""
        return self.batch_root / "final"

    @property
    def annotated_dir(self) -> Path:
        """返回标注可视化图片目录。"""
        return self.batch_root / "annotated"

    @property
    def crops_dir(self) -> Path:
        """返回裁切检查图目录。"""
        return self.batch_root / "crops"

    @property
    def template_regions_path(self) -> Path:
        """返回模板参考线图片路径。"""
        return self.annotated_dir / "_template_regions.jpg"

    def product_annotated_dir(self, product: str) -> Path:
        """返回单商品标注图片目录。"""
        return self.annotated_dir / product

    def product_crops_dir(self, product: str) -> Path:
        """返回单商品裁切图片目录。"""
        return self.crops_dir / product

    def product_final_dir(self, product: str) -> Path:
        """返回单商品最终图目录。"""
        return self.final_dir / product

    def grid_path(self, product: str, color: str) -> Path:
        """返回网格标注图路径。"""
        return self.product_annotated_dir(product) / f"{color}_grid.jpg"

    def skeleton_path(self, product: str, color: str) -> Path:
        """返回骨架标注图路径。"""
        return self.product_annotated_dir(product) / f"{color}_skeleton.jpg"

    def fill_input_path(self, product: str, color: str) -> Path:
        """返回生图补齐输入图路径。"""
        return self.product_annotated_dir(product) / f"{color}_fill_input.jpg"

    def fill_result_path(self, product: str, color: str) -> Path:
        """返回生图补齐结果图路径。"""
        return self.product_annotated_dir(product) / f"{color}_fill_result.jpg"

    @property
    def contact_sheet_path(self) -> Path:
        """返回最终成品拼接示例图路径。"""
        return self.annotated_dir / "_final_contact_sheet.jpg"

    def crop_path(self, product: str, color: str) -> Path:
        """返回裁切检查图路径。"""
        return self.product_crops_dir(product) / f"{color}_crop.jpg"

    def final_path(self, product: str, color: str, extension: str) -> Path:
        """返回最终交付图路径。"""
        return self.product_final_dir(product) / f"{color}{extension}"


def layout_from_annotations(annotations_path: Path) -> OutputLayout:
    """根据 annotations.json 路径反推批次输出布局。

    参数:
        annotations_path: 标注清单路径。
    返回值:
        输出路径布局实例。
    """
    return OutputLayout(annotations_path.resolve().parent)


def load_summary(layout: OutputLayout) -> dict[str, Any]:
    """读取批次 summary，不存在时返回空结构。

    参数:
        layout: 输出路径布局。
    返回值:
        summary 字典。
    """
    if layout.summary_path.exists():
        return read_json(layout.summary_path)
    return {"batch_root": str(layout.batch_root), "stages": {}}


def update_summary(layout: OutputLayout, stage: str, payload: dict[str, Any]) -> dict[str, Any]:
    """更新批次 summary 中的某个阶段信息。

    参数:
        layout: 输出路径布局。
        stage: 阶段名。
        payload: 阶段摘要数据。
    返回值:
        更新后的完整 summary。
    """
    summary = load_summary(layout)
    summary.setdefault("stages", {})[stage] = payload
    write_json(layout.summary_path, summary)
    return summary
