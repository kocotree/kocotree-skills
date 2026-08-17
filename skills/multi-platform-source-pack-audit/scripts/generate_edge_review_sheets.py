#!/usr/bin/env python3
"""为原始数据包图片生成四边和内部接缝审阅图。"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageOps

from cleanup_work import DEFAULT_WORK_DIR, cleanup_work_directory

LOGGER = logging.getLogger("edge_review_sheets")
DEFAULT_CONFIG = (
    Path(__file__).resolve().parent.parent
    / "assets"
    / "configs"
    / "visual-review-rules.json"
)
IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".bmp",
    ".gif",
    ".tif",
    ".tiff",
    ".avif",
}


def configure_logging(level: str) -> None:
    """配置标准日志输出。

    参数：
        level: 日志级别名称，例如 INFO 或 WARNING。

    返回值：
        无。
    """

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
    )


def load_config(config_path: Path) -> dict[str, Any]:
    """读取并验证视觉复核配置。

    参数：
        config_path: 视觉复核 JSON 配置路径。

    返回值：
        包含适用模块和审阅图参数的配置字典。
    """

    resolved_config = config_path.resolve()
    data = json.loads(resolved_config.read_text(encoding="utf-8"))
    required = {
        "edge_review_sheet_modules",
        "edge_strip_pixels",
        "edge_zoom",
        "max_review_width",
    }
    missing = sorted(required - set(data))
    if missing:
        raise ValueError(f"视觉复核配置缺少字段：{missing}")
    for field in ("edge_strip_pixels", "edge_zoom", "max_review_width"):
        if not isinstance(data[field], int) or data[field] <= 0:
            raise ValueError(f"视觉复核配置 {field} 必须是正整数")
    return data


def matches_path_scope(
    relative_parts: tuple[str, ...], configured_modules: list[str]
) -> bool:
    """判断相对路径是否包含配置指定的素材模块。"""

    scopes = {str(item).casefold() for item in configured_modules}
    path_parts = {part.casefold() for part in relative_parts[:-1]}
    return "*" in scopes or bool(path_parts & scopes)


def iter_review_images(
    root: Path,
    configured_modules: list[str],
    all_images: bool,
) -> Iterable[Path]:
    """按稳定顺序遍历需要生成审阅图的图片。

    参数：
        root: 原始数据包根目录。
        configured_modules: 默认需要生成审阅图的模块名称。
        all_images: 是否忽略模块范围并处理全部图片。

    返回值：
        经过路径排序的图片迭代器。
    """

    candidates: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.casefold() not in IMAGE_EXTENSIONS:
            continue
        relative_parts = path.relative_to(root).parts
        if all_images or matches_path_scope(relative_parts, configured_modules):
            candidates.append(path)
    return iter(sorted(candidates, key=lambda item: str(item).casefold()))


def flatten_image(image: Image.Image) -> Image.Image:
    """将图片转换为适合审阅图的 RGB 白底画面。"""

    transposed = ImageOps.exif_transpose(image)
    if "A" not in transposed.getbands() and "transparency" not in transposed.info:
        return transposed.convert("RGB")
    rgba = transposed.convert("RGBA")
    background = Image.new("RGBA", rgba.size, "white")
    background.alpha_composite(rgba)
    return background.convert("RGB")


def add_panel_label(
    draw: ImageDraw.ImageDraw, position: tuple[int, int], label: str
) -> None:
    """在审阅图中绘制 ASCII 面板标签。"""

    x, y = position
    draw.rectangle((x, y, x + 118, y + 22), fill="#111827")
    draw.text((x + 7, y + 5), label, fill="white")


def build_review_sheet(
    source: Image.Image,
    strip_pixels: int,
    edge_zoom: int,
    max_review_width: int,
    sequence: int,
) -> Image.Image:
    """组合完整图、四边放大条带和内部接缝审阅画面。

    参数：
        source: 已转换为 RGB 的原图。
        strip_pixels: 从原图四边截取的像素厚度。
        edge_zoom: 边缘条带的放大倍数。
        max_review_width: 完整图面板的最大显示宽度。
        sequence: 当前图片在本次任务中的序号。

    返回值：
        包含五个审阅区域的 RGB 图片。
    """

    width, height = source.size
    thickness_x = min(strip_pixels, width)
    thickness_y = min(strip_pixels, height)
    scale = min(1.0, max_review_width / width)
    review_width = max(1, round(width * scale))
    review_height = max(1, round(height * scale))
    horizontal_strip_height = max(1, thickness_y * edge_zoom)
    vertical_strip_width = max(1, thickness_x * edge_zoom)
    gap = 12
    header_height = 44
    label_height = 24
    canvas_width = vertical_strip_width * 2 + review_width + gap * 4
    canvas_height = (
        header_height
        + label_height * 3
        + horizontal_strip_height * 2
        + review_height
        + gap * 5
    )
    canvas = Image.new("RGB", (canvas_width, canvas_height), "#E5E7EB")
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, canvas_width, header_height), fill="#0F172A")
    draw.text((14, 14), f"EDGE REVIEW {sequence:04d}", fill="white")

    center_x = gap * 2 + vertical_strip_width
    y = header_height + gap
    add_panel_label(draw, (center_x, y), "TOP EDGE")
    y += label_height
    top = source.crop((0, 0, width, thickness_y)).resize(
        (review_width, horizontal_strip_height), Image.Resampling.NEAREST
    )
    canvas.paste(top, (center_x, y))
    draw.rectangle(
        (center_x, y, center_x + review_width - 1, y + horizontal_strip_height - 1),
        outline="#DC2626",
        width=2,
    )
    y += horizontal_strip_height + gap

    add_panel_label(draw, (center_x, y), "FULL / SEAMS")
    y += label_height
    full = source.resize((review_width, review_height), Image.Resampling.LANCZOS)
    left = source.crop((0, 0, thickness_x, height)).resize(
        (vertical_strip_width, review_height), Image.Resampling.NEAREST
    )
    right = source.crop((width - thickness_x, 0, width, height)).resize(
        (vertical_strip_width, review_height), Image.Resampling.NEAREST
    )
    left_x = gap
    right_x = center_x + review_width + gap
    canvas.paste(left, (left_x, y))
    canvas.paste(full, (center_x, y))
    canvas.paste(right, (right_x, y))
    for x, panel_width in (
        (left_x, vertical_strip_width),
        (center_x, review_width),
        (right_x, vertical_strip_width),
    ):
        draw.rectangle(
            (x, y, x + panel_width - 1, y + review_height - 1),
            outline="#DC2626",
            width=2,
        )
    add_panel_label(draw, (left_x, y), "LEFT EDGE")
    add_panel_label(draw, (right_x, y), "RIGHT EDGE")
    y += review_height + gap

    add_panel_label(draw, (center_x, y), "BOTTOM EDGE")
    y += label_height
    bottom = source.crop((0, height - thickness_y, width, height)).resize(
        (review_width, horizontal_strip_height), Image.Resampling.NEAREST
    )
    canvas.paste(bottom, (center_x, y))
    draw.rectangle(
        (center_x, y, center_x + review_width - 1, y + horizontal_strip_height - 1),
        outline="#DC2626",
        width=2,
    )
    return canvas


def safe_output_name(relative_path: str, sequence: int) -> str:
    """根据相对路径生成稳定的 PNG 文件名。"""

    stem = Path(relative_path).stem
    safe_stem = re.sub(r"[^\w.-]+", "-", stem, flags=re.UNICODE).strip("-_")
    safe_stem = safe_stem[:60] or "image"
    digest = hashlib.sha256(relative_path.encode("utf-8")).hexdigest()[:10]
    return f"{sequence:04d}-{safe_stem}-{digest}.png"


def generate_review_sheets(
    root: Path,
    output_dir: Path,
    config: dict[str, Any],
    all_images: bool,
    limit: int | None,
) -> dict[str, Any]:
    """生成边缘审阅图和源文件映射清单。

    参数：
        root: 原始数据包根目录。
        output_dir: 审阅图和映射清单输出目录。
        config: 已验证的视觉复核配置。
        all_images: 是否生成全包图片审阅图。
        limit: 最多处理图片数；为 None 时处理全部适用图片。

    返回值：
        包含输入、参数、数量和每张输出映射的汇总字典。
    """

    resolved_root = root.resolve()
    resolved_output = output_dir.resolve()
    if not resolved_root.is_dir():
        raise NotADirectoryError(f"原始数据包不可访问：{resolved_root}")
    if resolved_output.exists() and any(resolved_output.iterdir()):
        raise FileExistsError(f"审阅图输出目录必须为空：{resolved_output}")
    resolved_output.mkdir(parents=True, exist_ok=True)

    paths = list(
        iter_review_images(
            resolved_root,
            [str(item) for item in config["edge_review_sheet_modules"]],
            all_images,
        )
    )
    if limit is not None:
        paths = paths[:limit]
    records: list[dict[str, Any]] = []
    for sequence, path in enumerate(paths, start=1):
        relative_path = path.relative_to(resolved_root).as_posix()
        with Image.open(path) as image:
            source = flatten_image(image)
        sheet = build_review_sheet(
            source=source,
            strip_pixels=int(config["edge_strip_pixels"]),
            edge_zoom=int(config["edge_zoom"]),
            max_review_width=int(config["max_review_width"]),
            sequence=sequence,
        )
        output_name = safe_output_name(relative_path, sequence)
        output_path = resolved_output / output_name
        sheet.save(output_path, format="PNG", optimize=True)
        records.append(
            {
                "relative_path": relative_path,
                "module": Path(relative_path).parts[0],
                "source_width": source.width,
                "source_height": source.height,
                "review_sheet": str(output_path),
            }
        )
        LOGGER.info("已生成边缘审阅图 %s/%s：%s", sequence, len(paths), relative_path)

    manifest = {
        "schema_version": 1,
        "root": str(resolved_root),
        "output_dir": str(resolved_output),
        "all_images": all_images,
        "edge_strip_pixels": int(config["edge_strip_pixels"]),
        "edge_zoom": int(config["edge_zoom"]),
        "max_review_width": int(config["max_review_width"]),
        "image_count": len(records),
        "records": records,
    }
    manifest_path = resolved_output / "edge-review-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    LOGGER.info("边缘审阅图生成完成：图片=%s", len(records))
    return manifest


def parse_args() -> argparse.Namespace:
    """解析命令行参数。

    参数：
        无。

    返回值：
        包含输入、输出、配置和运行选项的参数对象。
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="原始数据包根目录")
    parser.add_argument("--output-dir", type=Path, required=True, help="审阅图输出目录")
    parser.add_argument(
        "--config", type=Path, default=DEFAULT_CONFIG, help="视觉复核配置"
    )
    parser.add_argument("--all-images", action="store_true", help="处理全包图片")
    parser.add_argument("--limit", type=int, help="最多处理图片数")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="日志级别",
    )
    return parser.parse_args()


def main() -> int:
    """执行边缘审阅图生成主流程。

    参数：
        无，参数从命令行读取。

    返回值：
        成功返回 0；配置、输入或图片处理失败时返回 1。
    """

    args = parse_args()
    configure_logging(args.log_level)
    if args.limit is not None and args.limit <= 0:
        LOGGER.error("--limit 必须是正整数")
        return 1
    try:
        cleanup_work_directory(
            work_dir=DEFAULT_WORK_DIR,
            protected_paths=[args.output_dir],
        )
        config = load_config(args.config)
        generate_review_sheets(
            root=args.root,
            output_dir=args.output_dir,
            config=config,
            all_images=args.all_images,
            limit=args.limit,
        )
        cleanup_work_directory(
            work_dir=DEFAULT_WORK_DIR,
            protected_paths=[args.output_dir],
        )
    except Exception:
        LOGGER.exception("边缘审阅图生成失败")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
