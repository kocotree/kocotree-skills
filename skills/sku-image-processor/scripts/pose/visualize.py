"""骨架辅助标注可视化。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from pose.annotation import COCO17_EDGES, point_is_valid
from pose.schema import PosePerson


def _load_font(size: int) -> ImageFont.ImageFont:
    """加载可显示中文的字体。

    参数:
        size: 字号大小。
    返回值:
        Pillow 字体对象。
    """
    candidates = [
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/simhei.ttf"),
        Path(__file__).resolve().parents[2] / "assets" / "方正兰亭中黑_GBK-Regular.ttf",
    ]
    for font_path in candidates:
        if font_path.exists():
            try:
                return ImageFont.truetype(str(font_path), size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def _draw_labeled_box(
    draw: ImageDraw.ImageDraw,
    box: list[int],
    label: str,
    color: tuple[int, int, int, int],
    width: int,
    font: ImageFont.ImageFont,
) -> None:
    """绘制带标签的矩形框。

    参数:
        draw: Pillow 绘图对象。
        box: [x1, y1, x2, y2]。
        label: 标签文字。
        color: RGBA 颜色。
        width: 线宽。
        font: 标签字体。
    返回值:
        无。
    """
    if not box:
        return
    draw.rectangle(tuple(box), outline=color, width=width)
    text_box = draw.textbbox((0, 0), label, font=font)
    label_width = text_box[2] - text_box[0] + 10
    label_height = text_box[3] - text_box[1] + 8
    label_x = max(0, box[0])
    label_y = max(0, box[1] - label_height)
    draw.rectangle((label_x, label_y, label_x + label_width, label_y + label_height), fill=(0, 0, 0, 180))
    draw.text((label_x + 5, label_y + 4), label, fill=(255, 255, 255, 255), font=font)


def draw_pose_result(image: Image.Image, people: list[PosePerson], drafts: list[dict[str, Any]], output_path: Path) -> None:
    """绘制骨架和人体语义参考框。

    参数:
        image: 原图或参考底图。
        people: 骨架检测结果。
        drafts: 每个人体对应的人体语义参考框草稿。
        output_path: 输出图片路径。
    返回值:
        无。
    """
    canvas = image.convert("RGB")
    draw = ImageDraw.Draw(canvas, "RGBA")
    width, height = canvas.size
    line_width = max(3, round(min(width, height) / 220))
    radius = max(4, round(min(width, height) / 180))
    font = _load_font(max(14, round(min(width, height) / 42)))

    for person, draft in zip(people, drafts):
        points = {point.index: point for point in person.keypoints if point_is_valid(point)}
        for start, end in COCO17_EDGES:
            if start not in points or end not in points:
                continue
            p1 = points[start]
            p2 = points[end]
            draw.line((p1.x, p1.y, p2.x, p2.y), fill=(0, 180, 255, 220), width=line_width)
        for point in points.values():
            draw.ellipse(
                (point.x - radius, point.y - radius, point.x + radius, point.y + radius),
                fill=(255, 230, 0, 230),
                outline=(30, 30, 30, 255),
            )
        _draw_labeled_box(draw, draft.get("body_box", []), "body_box", (0, 210, 220, 255), line_width, font)
        _draw_labeled_box(draw, draft.get("head_box", []), "head_box", (0, 160, 0, 255), line_width, font)
        _draw_labeled_box(draw, draft.get("garment_box", []), "garment_box", (255, 220, 0, 255), line_width, font)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, quality=95)
