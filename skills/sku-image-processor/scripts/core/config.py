"""工作流配置：模板各区域几何坐标 + 算法阈值。

与模板相关的几何坐标通过模板同名的 `<模板名>.layout.json` 提供，随模板一起替换；
代码内置一套默认值（对应自带模板）作为缺省，并负责加载与合并配置。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.utils import get_logger

logger = get_logger(__name__)

# 包围盒坐标类型：(x1, y1, x2, y2)
Box = tuple[int, int, int, int]


@dataclass
class TemplateLayout:
    """模板上各功能区域的像素坐标 (x1, y1, x2, y2)。

    这些坐标与具体模板图强相关，应随模板一起通过 JSON 配置提供。
    默认值对应仓库自带的 1440x1440 模板。
    """

    template_region: Box = (880, 320, 1410, 1120)   # 右侧贴片整体区域
    patch_box: Box = (923, 347, 1386, 1095)          # 贴片内容框
    safe_patch_zone: Box = (863, 347, 1386, 1095)    # 贴片危险区：模特/衣服不可侵入
    product_clean_box: Box = (970, 420, 1342, 925)   # 生成 clean_template 时需清空的商品区
    product_box: Box = (985, 420, 1325, 915)         # 透明商品图放置区
    text_clean_box: Box = (1008, 965, 1300, 1068)    # 清空旧文字时的内框
    text_box: Box = (1020, 986, 1288, 1066)          # 颜色名标签文字区
    green_label_box: Box = (924, 938, 1385, 1096)    # 绿色标签整体区


@dataclass
class WorkflowConfig:
    """服装 SKU 图片工作流的全部可调参数。"""

    canvas_size: int = 1440                  # 画布边长，运行时按模板实际尺寸覆盖
    background: tuple[int, int, int, int] = (235, 235, 235, 255)  # 模特图底色（RGBA）
    product_max_height: int = 485            # 透明商品图在贴片区的最大高度
    layout: TemplateLayout = field(default_factory=TemplateLayout)

def load_config(template_path: Path) -> WorkflowConfig:
    """加载工作流配置。

    优先读取与模板同名的 `<模板名>.layout.json`；找不到则使用内置默认值
    （对应自带模板），并记录警告。

    参数:
        template_path: 模板图片路径，用于推断同名配置文件。
    返回:
        合并外部配置后的 WorkflowConfig 实例。
    """
    config = WorkflowConfig()
    sidecar = template_path.with_name(template_path.stem + ".layout.json")
    if sidecar.exists():
        logger.info("加载模板配置文件: %s", sidecar)
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        _apply_overrides(config, data)
    else:
        logger.warning("未找到模板配置 %s，使用内置默认配置（对应自带模板）", sidecar)
    return config


def _apply_overrides(config: WorkflowConfig, data: dict[str, Any]) -> None:
    """用 JSON 字典覆盖配置字段。

    参数:
        config: 待覆盖的配置实例（原地修改）。
        data: 从 JSON 解析出的覆盖字典；其中 "layout" 子字典单独处理。
    """
    layout_data = data.pop("layout", None)
    for key, value in data.items():
        if key.startswith("_"):
            continue  # 下划线开头的键视为注释，忽略
        if hasattr(config, key):
            # JSON 中的数组在代码里统一用元组表示坐标/颜色
            setattr(config, key, tuple(value) if isinstance(value, list) else value)
        else:
            logger.warning("忽略未知配置项: %s", key)
    if isinstance(layout_data, dict):
        for key, value in layout_data.items():
            if hasattr(config.layout, key):
                setattr(config.layout, key, tuple(value))
            else:
                logger.warning("忽略未知模板区域配置项: layout.%s", key)
