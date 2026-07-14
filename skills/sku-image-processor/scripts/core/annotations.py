"""标注清单 annotations.json 的骨架生成、加载与校验。

清单由 prep 阶段生成骨架，agent 或视觉模型填写 crop_box 后，render 阶段消费。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image

from core.config import WorkflowConfig
from core.utils import collect_images, get_logger
from model.common import classify_model_background, find_scene_image

logger = get_logger(__name__)

MODEL_SUFFIXES = {".jpg", ".jpeg", ".png"}   # 模特图支持的扩展名
TRANSPARENT_SUFFIXES = {".png"}              # 透明商品图支持的扩展名


def _empty_annotation() -> dict[str, Any]:
    """构造一条待填的标注。"""
    return {"crop_box": []}


def is_product_dir(path: Path) -> bool:
    """判断目录是否是一个商品目录。

    参数:
        path: 待判断目录。
    返回:
        目录下含 `模特图/` 或 `透明图/` 时返回 True。
    """
    return path.is_dir() and ((path / "模特图").is_dir() or (path / "透明图").is_dir())


def iter_product_dirs(input_root: Path) -> list[Path]:
    """识别输入目录中的商品目录。

    支持两种结构：
    1. `<总文件夹>/<商品文件夹>/模特图|透明图|场景图`
    2. `<商品文件夹>/模特图|透明图|场景图`

    参数:
        input_root: 命令行传入的素材目录。
    返回:
        商品目录列表。
    """
    if is_product_dir(input_root):
        return [input_root]
    return sorted(path for path in input_root.iterdir() if is_product_dir(path))


def resolve_product_dir(input_root: Path, product_name: str) -> Path:
    """根据输入根目录和商品名定位商品目录。

    参数:
        input_root: 命令行传入的素材目录。
        product_name: annotations.json 中的商品名。
    返回:
        商品目录路径。
    """
    nested = input_root / product_name
    if is_product_dir(nested):
        return nested
    if is_product_dir(input_root) and input_root.name == product_name:
        return input_root
    return nested


def build_skeleton(input_root: Path, template_path: Path, cfg: WorkflowConfig) -> dict[str, Any]:
    """扫描输入目录，按颜色判定背景类别并生成标注清单骨架。

    参数:
        input_root: 素材目录，可为总目录或单商品目录。
        template_path: 模板图片路径，写入清单备查。
        cfg: 工作流配置（背景分类阈值）。
    返回:
        annotations 字典：{template, products:{商品:{颜色:{bg_class, source_image, source_size, annotation}}}}。
    """
    products: dict[str, Any] = {}
    product_dirs = iter_product_dirs(input_root)
    logger.info("识别到 %d 个商品目录", len(product_dirs))
    for product_dir in product_dirs:
        model_files = collect_images(product_dir / "模特图", MODEL_SUFFIXES)
        transparent_files = collect_images(product_dir / "透明图", TRANSPARENT_SUFFIXES)
        colors = sorted(set(model_files) | set(transparent_files))
        entry: dict[str, Any] = {}
        for color in colors:
            model_path = model_files.get(color)
            if model_path is None:
                # 只有透明商品图、没有模特图
                entry[color] = {
                    "bg_class": "no_model",
                    "source_image": "",
                    "source_size": [],
                    "annotation": None,
                }
                continue
            bg_class = classify_model_background(model_path)
            with Image.open(model_path) as image:
                source_size = [image.width, image.height]
            entry_item: dict[str, Any] = {
                "bg_class": bg_class,
                "source_image": str(model_path),
                "source_size": source_size,
                # 两类模特图都由 agent 标注裁切；transparent 还需同级场景图作背景
                "annotation": _empty_annotation(),
            }
            if bg_class == "transparent":
                scene = find_scene_image(model_path)
                entry_item["scene_image"] = str(scene) if scene else ""
                if scene is None:
                    logger.warning("透明模特图缺少同级 场景图/：%s/%s", product_dir.name, color)
            entry[color] = entry_item
            logger.info("分类 %s/%s -> %s", product_dir.name, color, bg_class)
        products[product_dir.name] = entry
    return {"template": str(template_path), "products": products}


def load_annotations(path: Path) -> dict[str, Any]:
    """加载标注清单。

    参数:
        path: annotations.json 路径。
    返回:
        清单字典。
    """
    import json

    return json.loads(path.read_text(encoding="utf-8"))


def annotation_is_valid(annotation: dict[str, Any] | None) -> bool:
    """判断一条 scene 标注是否已被有效填写。

    参数:
        annotation: 单个颜色的 annotation 字段。
    返回:
        crop_box 为 4 元坐标时为 True，否则 False。
    """
    if not annotation:
        return False
    crop_box = annotation.get("crop_box") or []
    if len(crop_box) != 4:
        return False
    return True
