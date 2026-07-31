from __future__ import annotations

import io
import logging
import os
import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

from .utils import ensure_dir, unique_path, add_image_record, add_failure, add_warning


logger = logging.getLogger(__name__)

PNGQUANT_质量档 = ["80-95", "70-90", "60-85", "45-75", "30-65", "15-50", "0-40"]
PNGQUANT_颜色档 = [256, 192, 128, 96, 64, 48, 32]
PNGQUANT_跳过退出码 = {98, 99}
PNGQUANT_单次超时秒数 = 60


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
    """保存并压缩符合平台大小要求的 PNG 图片。

    功能说明：先使用 Pillow 优化 PNG，再调用 pngquant 压缩并验收执行
    结果；处理记录写入逐图明细，异常和超限结果写入报告。

    参数：
        image：需要保存的图片对象。
        output：目标文件路径。
        max_bytes：平台允许的文件大小上限。
        report：当前运行的报告数据；为空时不记录报告。
        source：源图片路径。
        platform：目标平台名称。
        usage：图片用途。
        actions：保存前已执行的处理动作。
    返回值：
        成功时返回实际输出路径，保存失败时返回空值。
    """
    try:
        ensure_dir(output.parent)
        target = unique_path(output.with_suffix(".png"))
        image.save(target, format="PNG", optimize=True, compress_level=9)
        pngquant = find_pngquant()
        if pngquant:
            compression = compress_pngquant_under_limit(pngquant, target, max_bytes)
        else:
            size = target.stat().st_size
            compression = {
                "状态": "执行失败",
                "尝试次数": 0,
                "退出码": None,
                "输入大小KB": round(size / 1024, 2),
                "输出大小KB": round(size / 1024, 2),
                "限制KB": round(max_bytes / 1024, 2),
                "错误": "未找到 pngquant",
            }
            logger.error(
                "pngquant执行失败：未找到可执行文件 target=%r",
                str(target),
                extra={
                    "stage": "PNG压缩",
                    "event": "pngquant执行",
                    "status": "failed",
                },
            )
        if report is not None:
            action_list = list(actions or [])
            action_list.append("Pillow PNG优化压缩")
            action_list.append(f"pngquant压缩：{compression['状态']}")
            process_result = {
                "成功": "成功",
                "保留原图": "成功",
                "超出限制": "警告",
                "执行失败": "部分失败",
            }[compression["状态"]]
            add_image_record(
                report,
                source,
                target,
                platform,
                usage,
                action_list,
                {
                    "处理结果": process_result,
                    "PNG压缩": compression,
                },
            )
            if compression["状态"] == "执行失败":
                add_failure(
                    report,
                    "透明PNG压缩执行失败",
                    文件=str(target),
                    尝试次数=compression.get("尝试次数", 0),
                    退出码=compression.get("退出码"),
                    错误=compression.get("错误", ""),
                    提示="请通过 uv 安装 pngquant-cli 或设置 PNGQUANT_BIN",
                )
            if compression["状态"] == "超出限制":
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


@lru_cache(maxsize=1)
def find_pngquant() -> str | None:
    env_path = os.environ.get("PNGQUANT_BIN")
    if env_path:
        return env_path
    candidates = []
    executable_dir = Path(sys.executable).resolve().parent
    candidates.extend(
        [
            executable_dir / "pngquant.exe",
            executable_dir / "pngquant",
            executable_dir.parent / "bin" / "pngquant.exe",
            executable_dir.parent / "bin" / "pngquant",
            Path(__file__).resolve().parents[2] / "tools" / "pngquant.exe",
            Path(__file__).resolve().parents[2] / "tools" / "pngquant",
        ]
    )
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return shutil.which("pngquant")


def compress_pngquant_under_limit(
    pngquant: str,
    target: Path,
    max_bytes: int,
) -> dict[str, Any]:
    """调用 pngquant 并验证执行结果和文件大小。

    功能说明：按质量档和颜色档尝试压缩，校验退出码、输出文件和最终
    大小，并返回成功、保留原图、超出限制或执行失败。

    参数：
        pngquant：pngquant 可执行文件路径。
        target：Pillow 优化后的 PNG 文件路径。
        max_bytes：平台允许的文件大小上限。
    返回值：
        包含最终状态、尝试次数、退出码、大小和失败原因的结构化结果。
    """
    best = target
    original_size = target.stat().st_size
    best_size = original_size
    attempts = 0
    return_code: int | None = None
    error = ""

    for color_count in PNGQUANT_颜色档:
        for quality in PNGQUANT_质量档:
            attempts += 1
            tmp = target.with_suffix(f".q{quality.replace('-', '_')}.c{color_count}.png")
            if tmp.exists():
                tmp.unlink()
            command = [
                pngquant,
                str(color_count),
                "--force",
                "--skip-if-larger",
                "--output",
                str(tmp),
                "--quality",
                quality,
                str(target),
            ]
            try:
                result = subprocess.run(
                    command,
                    check=False,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=PNGQUANT_单次超时秒数,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                tmp.unlink(missing_ok=True)
                return_code = None
                error = str(exc)
                break

            return_code = result.returncode
            if return_code not in ({0} | PNGQUANT_跳过退出码):
                tmp.unlink(missing_ok=True)
                detail = (result.stderr or result.stdout).strip()
                error = detail[:500] or f"pngquant 退出码 {return_code}"
                break
            if return_code in PNGQUANT_跳过退出码:
                tmp.unlink(missing_ok=True)
                if best_size <= max_bytes:
                    break
                continue
            if not tmp.exists():
                error = "pngquant 返回成功但没有生成输出文件"
                break

            size = tmp.stat().st_size
            if size < best_size:
                if best != target:
                    best.unlink(missing_ok=True)
                best = tmp
                best_size = size
            else:
                tmp.unlink()
            if best_size <= max_bytes:
                break
        if error or best_size <= max_bytes:
            break

    used_candidate = best != target
    if used_candidate:
        best.replace(target)
    final_size = target.stat().st_size
    if error:
        status = "执行失败"
        log_level = logging.ERROR
    elif final_size > max_bytes:
        status = "超出限制"
        log_level = logging.WARNING
    elif used_candidate:
        status = "成功"
        log_level = logging.INFO
    else:
        status = "保留原图"
        log_level = logging.INFO

    logger.log(
        log_level,
        "pngquant处理完成 target=%r status=%s attempts=%d input_kb=%.2f output_kb=%.2f limit_kb=%.2f",
        str(target),
        status,
        attempts,
        original_size / 1024,
        final_size / 1024,
        max_bytes / 1024,
        extra={
            "stage": "PNG压缩",
            "event": "pngquant执行",
            "status": {
                "成功": "success",
                "保留原图": "success",
                "超出限制": "warning",
                "执行失败": "failed",
            }[status],
        },
    )
    compression = {
        "状态": status,
        "尝试次数": attempts,
        "退出码": return_code,
        "输入大小KB": round(original_size / 1024, 2),
        "输出大小KB": round(final_size / 1024, 2),
        "限制KB": round(max_bytes / 1024, 2),
    }
    if error:
        compression["错误"] = error
    return compression


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
