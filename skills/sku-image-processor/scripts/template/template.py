"""模板处理：采样绿色标签色、生成 clean_template、绘制调试参考线图。

clean_template 是在原始模板基础上清空商品区与旧文字、但保留绿色标签外形的「干净底板」，
后续每个 SKU 图都在它之上合成商品图与颜色名，避免重画模板视觉元素。
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from core.config import WorkflowConfig
from core.utils import get_logger, read_json, write_json

logger = get_logger(__name__)


def sample_green(template: Image.Image) -> list[int]:
    """从模板中采样绿色标签的代表色。

    参数:
        template: RGBA 模板图像。
    返回:
        绿色 [R, G, B]；采样不到时返回兜底绿色。
    """
    arr = np.array(template.convert("RGBA"))
    rgb = arr[:, :, :3]
    alpha = arr[:, :, 3]
    mask = (alpha > 0) & (rgb[:, :, 1] > 120) & (rgb[:, :, 0] < 100) & (rgb[:, :, 2] < 130)
    if not np.any(mask):
        logger.warning("模板中未采样到绿色标签像素，使用兜底绿色")
        return [48, 162, 77]
    return [int(value) for value in np.median(rgb[mask], axis=0)]


def build_clean_template(template: Image.Image, cfg: WorkflowConfig) -> tuple[Image.Image, list[int]]:
    """生成 clean_template：清空商品区、复原标签文字内框，保留标签外形。

    参数:
        template: RGBA 模板图像。
        cfg: 工作流配置（用于各区域坐标）。
    返回:
        (clean_template 图像, 采样到的绿色 [R, G, B])。
    """
    clean = template.copy()
    draw = ImageDraw.Draw(clean)
    # 把商品展示区涂白，便于后续放置透明商品图
    draw.rectangle(cfg.layout.product_clean_box, fill=(255, 255, 255, 255))
    green = sample_green(template)
    _restore_label_text_area(clean, cfg, green)
    logger.info("已生成 clean_template，标签绿色=%s", green)
    return clean, green


def _restore_label_text_area(layer: Image.Image, cfg: WorkflowConfig, green: list[int]) -> None:
    """只清空绿色标签内部的文字框，保留标签外部的曲线轮廓。

    参数:
        layer: 需要原地修改的图层（RGBA）。
        cfg: 工作流配置（用于文字框坐标）。
        green: 标签兜底绿色 [R, G, B]。
    """
    arr = np.array(layer.convert("RGBA"))
    x1, y1, x2, y2 = cfg.layout.text_box
    region = arr[y1:y2, x1:x2]
    rgb = region[:, :, :3]
    alpha = region[:, :, 3]
    green_mask = (alpha > 0) & (rgb[:, :, 1] > 100) & (rgb[:, :, 0] < 120) & (rgb[:, :, 2] < 150)
    if np.any(green_mask):
        fill = np.median(rgb[green_mask], axis=0).astype(np.uint8)
    else:
        fill = np.array(green, dtype=np.uint8)

    # 文字框位于绿色标签内部，只重涂这个内矩形，让带抗锯齿的旧字消失，
    # 同时绝不重画标签外部的曲线外形。
    region[:, :, :3] = fill
    region[:, :, 3] = 255
    arr[y1:y2, x1:x2] = region
    layer.paste(Image.fromarray(arr, "RGBA"))


def draw_template_regions(clean_template: Image.Image, cfg: WorkflowConfig) -> Image.Image:
    """在 clean_template 上画出各功能区参考线，用于调试核对坐标。

    参数:
        clean_template: 干净模板图像。
        cfg: 工作流配置（各区域坐标、背景色）。
    返回:
        带彩色参考框的 RGB 图像。
    """
    size = cfg.canvas_size
    canvas = Image.alpha_composite(
        Image.new("RGBA", (size, size), cfg.background),
        clean_template,
    ).convert("RGB")
    draw = ImageDraw.Draw(canvas, "RGBA")
    draw.rectangle(cfg.layout.template_region, outline=(255, 0, 0, 255), width=4)
    draw.rectangle(cfg.layout.safe_patch_zone, fill=(255, 0, 0, 45), outline=(255, 0, 0, 255), width=3)
    draw.rectangle(cfg.layout.product_box, outline=(0, 80, 255, 255), width=4)
    draw.rectangle(cfg.layout.green_label_box, outline=(0, 190, 70, 255), width=4)
    draw.rectangle(cfg.layout.text_box, outline=(255, 220, 0, 255), width=4)
    return canvas


def _sha256(path: Path) -> str:
    """计算文件内容的 sha256，文件不存在返回 'none'。"""
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "none"


def _cache_signature(template_path: Path) -> dict[str, str]:
    """生成模板缓存签名：模板图与同名 layout.json 的内容哈希。

    参数:
        template_path: 模板图片路径。
    返回:
        {"template_sha": ..., "layout_sha": ...}；任一内容变化即缓存失效。
    """
    layout_path = template_path.with_name(template_path.stem + ".layout.json")
    return {"template_sha": _sha256(template_path), "layout_sha": _sha256(layout_path)}


def _signature_matches(meta: dict, signature: dict[str, str]) -> bool:
    """判断已存缓存的签名是否与当前模板/配置一致。"""
    return meta.get("template_sha") == signature["template_sha"] and meta.get("layout_sha") == signature["layout_sha"]


def get_clean_template(template_path: Path, cfg: WorkflowConfig) -> tuple[Image.Image, list[int]]:
    """获取 clean_template：命中缓存则直接读取，否则生成并缓存到模板同目录。

    缓存文件：`<模板名>.clean.png` 与 `<模板名>.cache.json`，随模板复用，
    仅在模板图或 layout.json 内容变化时重建。

    参数:
        template_path: 模板图片路径。
        cfg: 工作流配置。
    返回:
        (clean_template 图像, 采样到的绿色 [R, G, B])。
    """
    cache_png = template_path.with_name(template_path.stem + ".clean.png")
    meta_path = template_path.with_name(template_path.stem + ".cache.json")
    signature = _cache_signature(template_path)
    if cache_png.exists() and meta_path.exists():
        meta = read_json(meta_path)
        if _signature_matches(meta, signature):
            logger.info("复用缓存 clean_template: %s", cache_png)
            clean = Image.open(cache_png).convert("RGBA")
            return clean, meta.get("sampled_green") or sample_green(clean)

    template = Image.open(template_path).convert("RGBA")
    clean, green = build_clean_template(template, cfg)
    clean.save(cache_png)
    write_json(meta_path, {**signature, "sampled_green": green})
    logger.info("生成并缓存 clean_template: %s", cache_png)
    return clean, green


def get_template_regions(template_path: Path, clean_template: Image.Image, cfg: WorkflowConfig) -> Image.Image:
    """获取模板参考线图：命中缓存则直接读取，否则生成并缓存到模板同目录。

    缓存文件：`<模板名>.regions.jpg`，签名沿用 clean 的 `<模板名>.cache.json`。

    参数:
        template_path: 模板图片路径。
        clean_template: 干净模板图层（缓存未命中时用于绘制）。
        cfg: 工作流配置。
    返回:
        带彩色参考框的 RGB 图像。
    """
    cache_jpg = template_path.with_name(template_path.stem + ".regions.jpg")
    meta_path = template_path.with_name(template_path.stem + ".cache.json")
    signature = _cache_signature(template_path)
    if cache_jpg.exists() and meta_path.exists():
        meta = read_json(meta_path)
        if _signature_matches(meta, signature) and meta.get("regions_cached"):
            logger.info("复用缓存参考线图: %s", cache_jpg)
            return Image.open(cache_jpg).convert("RGB")

    regions = draw_template_regions(clean_template, cfg)
    regions.save(cache_jpg, quality=95)
    meta = read_json(meta_path) if meta_path.exists() else dict(signature)
    meta.update(signature)
    meta["regions_cached"] = True
    write_json(meta_path, meta)
    logger.info("生成并缓存参考线图: %s", cache_jpg)
    return regions
