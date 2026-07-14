"""模特图放置的共用能力：背景判定、合成参考底图和裁切校验。

模特图分两类：
- opaque：自带背景（棚拍/实景），原样裁切，不做任何背景处理。
- transparent：抠像无背景，用同级 `场景图/` 作为背景合成。
"""
from __future__ import annotations

from pathlib import Path
import numpy as np
from PIL import Image

from core.config import WorkflowConfig
from core.utils import get_logger

logger = get_logger(__name__)

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}


def classify_model_background(image_path: Path) -> str:
    """判定模特图是否自带背景。

    参数:
        image_path: 模特图路径。
    返回:
        "transparent"（含透明像素、需场景图）或 "opaque"（自带背景）。
    """
    image = Image.open(image_path)
    has_alpha = image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info)
    if has_alpha and bool((np.array(image.convert("RGBA").getchannel("A")) < 255).any()):
        return "transparent"
    return "opaque"


def find_scene_image(source_path: Path) -> Path | None:
    """查找透明模特图的背景：模特图同级 `场景图/` 下的第一张图。

    参数:
        source_path: 模特图路径（<商品>/模特图/<颜色>.png）。
    返回:
        场景图路径；不存在返回 None。
    """
    scene_dir = source_path.parent.parent / "场景图"
    if not scene_dir.exists():
        return None
    for path in sorted(scene_dir.iterdir()):
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES:
            return path
    return None


def prepare_image(source_path: Path, bg_class: str, cfg: WorkflowConfig) -> Image.Image:
    """返回用于裁切/标注的参考底图（RGB，模特图原分辨率）。

    opaque 直接用模特图原照片（自带背景，不动任何像素）；
    transparent 把模特合成到「同级场景图」上（场景图缩放到模特尺寸）。

    参数:
        source_path: 模特图路径。
        bg_class: "opaque" 或 "transparent"。
        cfg: 工作流配置（保留以统一签名）。
    返回:
        RGB 全幅参考图，尺寸与模特图一致，源坐标 crop_box 直接适用。
    """
    image = Image.open(source_path)
    if bg_class != "transparent":
        return image.convert("RGB")
    model = image.convert("RGBA")
    scene_path = find_scene_image(source_path)
    if scene_path is None:
        raise FileNotFoundError(f"透明模特图缺少同级 场景图/：{source_path}")
    base = Image.open(scene_path).convert("RGB").resize(model.size).convert("RGBA")
    base.alpha_composite(model)
    return base.convert("RGB")


def crop_without_extension(image: Image.Image, crop_box: tuple[int, int, int, int]) -> Image.Image:
    """裁剪已确认不需要补背景的图片。

    参数:
        image: 源图（RGB）。
        crop_box: 位于源图范围内的裁剪框。
    返回:
        裁剪结果。
    """
    width, height = image.size
    x1, y1, x2, y2 = crop_box
    if x1 < 0 or y1 < 0 or x2 > width or y2 > height:
        raise ValueError(f"crop_box 需要先补背景再裁切: {crop_box}, source={width}x{height}")
    return image.crop(crop_box)
