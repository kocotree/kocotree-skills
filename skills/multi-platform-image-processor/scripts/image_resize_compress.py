from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageOps

from common import ensure_dir, unique_path, add_image_record, add_failure, add_warning


PNGQUANT_质量档 = ["80-95", "70-90", "60-85", "45-75", "30-65", "15-50", "0-40"]
PNGQUANT_颜色档 = [256, 192, 128, 96, 64, 48, 32]


def open_image(path: Path) -> Image.Image:
    with Image.open(path) as img:
        return ImageOps.exif_transpose(img).copy()


def to_rgb(image: Image.Image, background: tuple[int, int, int] = (255, 255, 255)) -> Image.Image:
    if image.mode in ("RGBA", "LA") or "transparency" in image.info:
        rgba = image.convert("RGBA")
        canvas = Image.new("RGBA", rgba.size, (*background, 255))
        canvas.alpha_composite(rgba)
        return canvas.convert("RGB")
    return image.convert("RGB")


def fit_into_canvas(image: Image.Image, size: tuple[int, int], background: tuple[int, int, int] = (255, 255, 255)) -> Image.Image:
    target_w, target_h = size
    src_w, src_h = image.size
    scale = min(target_w / src_w, target_h / src_h)
    new_size = (max(1, round(src_w * scale)), max(1, round(src_h * scale)))
    resized = image.resize(new_size, Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", size, background)
    canvas.paste(to_rgb(resized, background), ((target_w - new_size[0]) // 2, (target_h - new_size[1]) // 2))
    return canvas


def save_jpg_under(
    image: Image.Image,
    output: Path,
    max_bytes: int,
    report: dict | None = None,
    source: Path | None = None,
    platform: str = "",
    usage: str = "",
    actions: list[str] | None = None,
) -> Path | None:
    try:
        ensure_dir(output.parent)
        target = unique_path(output.with_suffix(".jpg"))
        rgb = to_rgb(image)
        chosen_bytes = None
        chosen_quality = None
        for quality in range(92, 29, -5):
            buffer = io.BytesIO()
            rgb.save(buffer, format="JPEG", quality=quality, optimize=True, progressive=True)
            data = buffer.getvalue()
            chosen_bytes = data
            chosen_quality = quality
            if len(data) <= max_bytes:
                break
        target.write_bytes(chosen_bytes or b"")
        if report is not None:
            action_list = list(actions or [])
            action_list.append(f"JPG压缩质量{chosen_quality}")
            add_image_record(report, source, target, platform, usage, action_list)
            if target.stat().st_size > max_bytes:
                add_warning(
                    report,
                    "JPG压缩后仍超过大小限制",
                    文件=str(target),
                    限制KB=round(max_bytes / 1024, 2),
                    实际KB=round(target.stat().st_size / 1024, 2),
                )
        return target
    except Exception as exc:
        if report is not None:
            add_failure(report, "保存JPG失败", 源文件=str(source or ""), 输出文件=str(output), 错误=str(exc))
        return None


def save_png_under(
    image: Image.Image,
    output: Path,
    max_bytes: int,
    report: dict | None = None,
    source: Path | None = None,
    platform: str = "",
    usage: str = "",
    actions: list[str] | None = None,
) -> Path | None:
    try:
        ensure_dir(output.parent)
        target = unique_path(output.with_suffix(".png"))
        image.save(target, format="PNG", optimize=True, compress_level=9)
        pngquant = find_pngquant()
        pngquant_action = "未找到pngquant"
        if pngquant:
            pngquant_action = compress_pngquant_under_limit(pngquant, target, max_bytes)
        if report is not None:
            action_list = list(actions or [])
            action_list.append("Pillow PNG优化压缩")
            action_list.append(pngquant_action)
            add_image_record(report, source, target, platform, usage, action_list)
            if not pngquant:
                add_failure(report, "透明PNG压缩缺少pngquant", 文件=str(target), 提示="请通过uv安装pngquant-cli或设置PNGQUANT_BIN")
            if target.stat().st_size > max_bytes:
                add_warning(
                    report,
                    "PNG压缩后仍超过大小限制",
                    文件=str(target),
                    限制KB=round(max_bytes / 1024, 2),
                    实际KB=round(target.stat().st_size / 1024, 2),
                )
        return target
    except Exception as exc:
        if report is not None:
            add_failure(report, "保存PNG失败", 源文件=str(source or ""), 输出文件=str(output), 错误=str(exc))
        return None


def find_pngquant() -> str | None:
    env_path = os.environ.get("PNGQUANT_BIN")
    candidates = []
    if env_path:
        candidates.append(Path(env_path))
    executable_dir = Path(sys.executable).resolve().parent
    candidates.extend(
        [
            executable_dir / "pngquant.exe",
            executable_dir / "pngquant",
            executable_dir.parent / "bin" / "pngquant.exe",
            executable_dir.parent / "bin" / "pngquant",
            Path(__file__).resolve().parents[1] / "tools" / "pngquant.exe",
            Path(__file__).resolve().parents[1] / "tools" / "pngquant",
        ]
    )
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return shutil.which("pngquant")


def compress_pngquant_under_limit(pngquant: str, target: Path, max_bytes: int) -> str:
    best = target
    best_size = target.stat().st_size
    used_quality = "未执行"
    for color_count in PNGQUANT_颜色档:
        for quality in PNGQUANT_质量档:
            tmp = target.with_suffix(f".q{quality.replace('-', '_')}.c{color_count}.png")
            if tmp.exists():
                tmp.unlink()
            result = subprocess.run(
                [
                    pngquant,
                    str(color_count),
                    "--force",
                    "--skip-if-larger",
                    "--output",
                    str(tmp),
                    "--quality",
                    quality,
                    str(target),
                ],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if tmp.exists():
                size = tmp.stat().st_size
                if size < best_size:
                    if best != target and best.exists():
                        best.unlink()
                    best = tmp
                    best_size = size
                    used_quality = f"{quality},颜色{color_count}"
                elif tmp != best:
                    tmp.unlink()
                if best_size <= max_bytes:
                    break
            elif result.returncode == 99:
                used_quality = f"{quality},颜色{color_count}未达到质量下限"
        if best_size <= max_bytes:
            break
    if best != target:
        best.replace(target)
    return f"pngquant压缩质量{used_quality}"


def process_jpg_canvas(
    source: Path,
    output: Path,
    size: tuple[int, int],
    max_bytes: int,
    report: dict,
    platform: str,
    usage: str,
) -> Path | None:
    try:
        image = open_image(source)
        canvas = fit_into_canvas(image, size)
        return save_jpg_under(canvas, output, max_bytes, report, source, platform, usage, [f"等比放入{size[0]}x{size[1]}画布"])
    except Exception as exc:
        add_failure(report, "处理JPG画布失败", 源文件=str(source), 输出文件=str(output), 错误=str(exc))
        return None


def process_jpg_original_or_compress(
    source: Path,
    output: Path,
    max_bytes: int,
    report: dict,
    platform: str,
    usage: str,
) -> Path | None:
    try:
        image = open_image(source)
        return save_jpg_under(image, output, max_bytes, report, source, platform, usage, ["保持视觉尺寸并压缩"])
    except Exception as exc:
        add_failure(report, "处理JPG压缩失败", 源文件=str(source), 输出文件=str(output), 错误=str(exc))
        return None


def process_png_original_or_compress(
    source: Path,
    output: Path,
    max_bytes: int,
    report: dict,
    platform: str,
    usage: str,
) -> Path | None:
    try:
        image = open_image(source).convert("RGBA")
        return save_png_under(image, output, max_bytes, report, source, platform, usage, ["保持透明通道并压缩"])
    except Exception as exc:
        add_failure(report, "处理PNG压缩失败", 源文件=str(source), 输出文件=str(output), 错误=str(exc))
        return None


def resize_width_jpg(
    source: Path,
    output: Path,
    width: int,
    max_bytes: int,
    report: dict,
    platform: str,
    usage: str,
) -> Path | None:
    try:
        image = open_image(source)
        ratio = width / image.width
        resized = image.resize((width, max(1, round(image.height * ratio))), Image.Resampling.LANCZOS)
        return save_jpg_under(resized, output, max_bytes, report, source, platform, usage, [f"等比缩放到宽{width}px"])
    except Exception as exc:
        add_failure(report, "按宽度缩放JPG失败", 源文件=str(source), 输出文件=str(output), 错误=str(exc))
        return None
