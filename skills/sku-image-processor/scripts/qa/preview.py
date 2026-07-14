"""输出与可视化：保存图片、绘制裁切框、生成交付总览图。"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

from core.utils import get_logger

logger = get_logger(__name__)


def save_preview(canvas: Image.Image, path: Path, extension: str) -> None:
    """保存画布；.png 保留透明，其余按高质量 JPEG 输出。

    参数:
        canvas: 待保存图像。
        path: 输出路径。
        extension: 扩展名（含点），用于决定保存格式。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if extension.lower() == ".png":
        canvas.save(path)
    else:
        canvas.convert("RGB").save(path, quality=95, subsampling=1)


def draw_crop_box(image: Image.Image, crop_box: tuple[int, int, int, int]) -> Image.Image:
    """在标注图上用红框标出 crop_box 实际裁切范围。

    参数:
        image: 骨架标注图；缺少骨架图时可使用 render 实际底图。
        crop_box: 源图坐标裁切框，可越出源图边界。
    返回:
        带红色裁切框的 RGB 图像；越界时扩展画布展示完整框。
    """
    source = image.convert("RGB")
    x1, y1, x2, y2 = crop_box
    min_x = min(0, x1)
    min_y = min(0, y1)
    max_x = max(source.width, x2)
    max_y = max(source.height, y2)
    offset_x = -min_x
    offset_y = -min_y
    canvas = Image.new("RGB", (max_x - min_x, max_y - min_y), (245, 245, 245))
    canvas.paste(source, (offset_x, offset_y))
    draw = ImageDraw.Draw(canvas, "RGBA")
    line_width = max(4, round(min(canvas.size) / 180))
    draw.rectangle(
        (x1 + offset_x, y1 + offset_y, x2 + offset_x, y2 + offset_y),
        outline=(255, 0, 0, 255),
        width=line_width,
    )
    return canvas


def build_contact_sheet(output_root: Path, out_path: Path) -> None:
    """把所有交付图片拼成一张总览缩略图，便于整体检查。

    参数:
        output_root: 交付图根目录（按商品目录分类）。
        out_path: 总览图输出路径。
    """
    images: list[tuple[str, str, Path]] = []
    for product_dir in sorted(path for path in output_root.iterdir() if path.is_dir()):
        final_images = list(product_dir.glob("*.jpg")) + list(product_dir.glob("*.png"))
        for image_path in sorted(final_images):
            images.append((product_dir.name, image_path.stem, image_path))
    if not images:
        out_path.unlink(missing_ok=True)
        logger.info("没有可用于总览图的交付图片，跳过")
        return
    thumb = 260          # 缩略图边长
    label_height = 60    # 每格底部文字区高度
    cols = 3
    rows = math.ceil(len(images) / cols)
    sheet = Image.new("RGB", (cols * thumb, rows * (thumb + label_height)), "white")
    draw = ImageDraw.Draw(sheet)
    for index, (product, color, path) in enumerate(images):
        row = index // cols
        col = index % cols
        x = col * thumb
        y = row * (thumb + label_height)
        image = Image.open(path).convert("RGB")
        image.thumbnail((thumb, thumb), Image.Resampling.LANCZOS)
        sheet.paste(image, (x + (thumb - image.width) // 2, y + (thumb - image.height) // 2))
        draw.rectangle((x, y, x + thumb - 1, y + thumb - 1), outline=(210, 210, 210))
        draw.text((x + 4, y + thumb + 2), product[:18], fill=(0, 0, 0))
        draw.text((x + 4, y + thumb + 22), color, fill=(0, 0, 0))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path, quality=92)
    logger.info("已生成交付总览图: %s（共 %d 张）", out_path, len(images))
