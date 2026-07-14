"""生成式背景补全：把 crop_box 越界产生的缺口交给图像生成模型填充。

默认策略：把完整方形裁切图中的越界缺口涂成品红哨兵色 #FF00FF，
直接发给模型补成一张完整图片，并整体采用模型返回结果，避免局部贴回造成硬接缝。
失败时返回 None，由调用方决定报错或重试。

参数:
    image: 源图（RGB）。
    crop_box: 裁剪框（可超出源图）。
    output_dir: 生图调试图片输出目录。
返回:
    成功 → 填充后的裁切图（PIL Image）；失败 → None。
"""
from __future__ import annotations

import io
import json
import time
from pathlib import Path
from typing import Any

import numpy as np
import requests
from PIL import Image

from core.auth import get_headers, with_auth
from core.utils import get_logger

logger = get_logger(__name__)

BASE_URL = "https://text-image-field-shortcut.skills.kktree.cn"
ENDPOINT = "/api/generate-image"
MODEL = "gemini-3.1-flash-image-preview"
TIMEOUT = 240

MAGENTA = (255, 0, 255)
# 缺口外扩：向有像素的方向取多少真实像素作为上下文（像素）
GAP_CONTEXT_MARGIN = 520
PROMPT = """
Fill only the magenta (#FF00FF) missing area as an inpainting task.
The result must look like the same continuous original photograph, not a pasted second image.
Extend the exact surrounding scene from the non-magenta pixels: keep the same sky gradient, horizon line, sea or beach perspective, blur level, lens texture, lighting direction, color temperature, contrast, grain, and depth of field.
Do not invent a new beach, new ocean, new wall, new picture frame, new vertical panel, new border, or a different camera angle.
Do not alter any non-magenta pixels. Do not change the child, clothing, hands, hair, hat, props, product, or any foreground subject.
There must be no visible seam, hard vertical/horizontal boundary, collage edge, magenta residue, repeated tile, or unrelated scenery.
""".strip()


def _compute_gaps(
    crop_box: tuple[int, int, int, int], src_w: int, src_h: int
) -> dict[str, int]:
    """计算 crop_box 在上下左右各超出源图多少像素。

    参数:
        crop_box: (x1, y1, x2, y2) 裁剪框。
        src_w: 源图宽。
        src_h: 源图高。
    返回:
        {"left": px, "top": px, "right": px, "bottom": px}，0 表示不越界。
    """
    x1, y1, x2, y2 = crop_box
    return {
        "left": max(0, -x1),
        "top": max(0, -y1),
        "right": max(0, x2 - src_w),
        "bottom": max(0, y2 - src_h),
    }


def _build_magenta_crop(
    image: Image.Image, crop_box: tuple[int, int, int, int]
) -> tuple[Image.Image, dict[str, int]]:
    """裁切源图，越界区域填品红。

    参数:
        image: 源图（RGB）。
        crop_box: 裁剪框。
    返回:
        (带品红缺口的裁切图, gaps 字典)。
    """
    w, h = image.size
    x1, y1, x2, y2 = crop_box
    crop_w, crop_h = x2 - x1, y2 - y1
    gaps = _compute_gaps(crop_box, w, h)

    canvas = Image.new("RGB", (crop_w, crop_h), MAGENTA)
    src_region = (max(0, x1), max(0, y1), min(w, x2), min(h, y2))
    if src_region[2] <= src_region[0] or src_region[3] <= src_region[1]:
        raise ValueError(f"crop_box 必须与源图有重叠区域: {crop_box}, source={w}x{h}")
    real_pixels = image.crop(src_region)
    paste_x = gaps["left"]
    paste_y = gaps["top"]
    canvas.paste(real_pixels, (paste_x, paste_y))
    return canvas, gaps


def _extract_patch(
    magenta_crop: Image.Image, gaps: dict[str, int], margin: int = GAP_CONTEXT_MARGIN
) -> tuple[Image.Image, tuple[int, int, int, int]]:
    """从带品红的裁切图中提取「缺口 + 周边上下文」小片。

    只取包含品红区域及其周边 margin 像素的最小矩形，减少发送给模型的图片大小。

    参数:
        magenta_crop: 带品红缺口的裁切图。
        gaps: 各边缺口尺寸。
        margin: 向真实像素方向外扩的上下文像素数。
    返回:
        (小片图, 小片在裁切图中的位置 (px1, py1, px2, py2))。
    """
    cw, ch = magenta_crop.size

    # 品红区域的边界（可能跨多边）
    arr = np.array(magenta_crop)
    magenta_mask = (arr[:, :, 0] == 255) & (arr[:, :, 1] == 0) & (arr[:, :, 2] == 255)
    ys, xs = np.where(magenta_mask)
    if len(ys) == 0:
        return magenta_crop, (0, 0, cw, ch)

    dynamic_margin = max(margin, round(min(cw, ch) * 0.35))

    # 品红区域外扩上下文；如果缺口贯穿某个方向，保留完整长边以维持地平线和透视连续。
    px1 = max(0, int(xs.min()) - dynamic_margin)
    py1 = max(0, int(ys.min()) - dynamic_margin)
    px2 = min(cw, int(xs.max()) + 1 + dynamic_margin)
    py2 = min(ch, int(ys.max()) + 1 + dynamic_margin)
    if gaps.get("left") or gaps.get("right"):
        py1, py2 = 0, ch
    if gaps.get("top") or gaps.get("bottom"):
        px1, px2 = 0, cw

    patch = magenta_crop.crop((px1, py1, px2, py2))
    return patch, (px1, py1, px2, py2)


def _magenta_mask(image: Image.Image) -> Image.Image:
    """生成品红缺口的灰度 mask。"""
    arr = np.array(image)
    mask = ((arr[:, :, 0] == 255) & (arr[:, :, 1] == 0) & (arr[:, :, 2] == 255)).astype(np.uint8) * 255
    return Image.fromarray(mask, mode="L")


def _remove_magenta_residue(image: Image.Image, repair_mask: Image.Image) -> Image.Image:
    """清理补图区域内的品红残留像素。

    参数:
        image: 已贴回生成结果的裁切图。
        repair_mask: 原始缺口区域 mask，仅在该区域内清理。
    返回值:
        清理后的裁切图。
    """
    arr = np.array(image.convert("RGB"))
    mask = np.array(repair_mask.convert("L")) > 0
    magenta_like = (arr[:, :, 0] > 180) & (arr[:, :, 1] < 110) & (arr[:, :, 2] > 150)
    targets = mask & magenta_like
    if not np.any(targets):
        return image

    repaired = arr.copy()
    height, width = targets.shape
    ys, xs = np.where(targets)
    for y, x in zip(ys, xs):
        y1, y2 = max(0, y - 2), min(height, y + 3)
        x1, x2 = max(0, x - 2), min(width, x + 3)
        local = arr[y1:y2, x1:x2]
        local_bad = magenta_like[y1:y2, x1:x2]
        neighbors = local[~local_bad]
        if len(neighbors):
            repaired[y, x] = np.median(neighbors, axis=0)
    logger.warning("已清理补图区域品红残留像素: %d", len(xs))
    return Image.fromarray(repaired, mode="RGB")


def _estimate_seam_delta(original_patch: Image.Image, generated_patch: Image.Image) -> float:
    """估算缺口边界两侧的颜色差，用于提示明显割裂风险。"""
    original = np.array(original_patch.convert("RGB"), dtype=np.float32)
    generated = np.array(generated_patch.convert("RGB"), dtype=np.float32)
    magenta = (original[:, :, 0] == 255) & (original[:, :, 1] == 0) & (original[:, :, 2] == 255)
    if not np.any(magenta):
        return 0.0

    real = ~magenta
    real_boundary = np.zeros_like(magenta)
    fill_boundary = np.zeros_like(magenta)
    real_boundary[:, :-1] |= real[:, :-1] & magenta[:, 1:]
    real_boundary[:, 1:] |= real[:, 1:] & magenta[:, :-1]
    real_boundary[:-1, :] |= real[:-1, :] & magenta[1:, :]
    real_boundary[1:, :] |= real[1:, :] & magenta[:-1, :]
    fill_boundary[:, 1:] |= magenta[:, 1:] & real[:, :-1]
    fill_boundary[:, :-1] |= magenta[:, :-1] & real[:, 1:]
    fill_boundary[1:, :] |= magenta[1:, :] & real[:-1, :]
    fill_boundary[:-1, :] |= magenta[:-1, :] & real[1:, :]
    if not np.any(real_boundary) or not np.any(fill_boundary):
        return 0.0

    real_mean = original[real_boundary].mean(axis=0)
    fill_mean = generated[fill_boundary].mean(axis=0)
    return float(np.abs(real_mean - fill_mean).mean())


@with_auth
def _api_request(url: str, fields: dict[str, Any], patch_bytes: bytes) -> requests.Response:
    """发送图片生成请求（带认证）。"""
    buffer = io.BytesIO(patch_bytes)
    files = [("files", ("fill_input.png", buffer, "image/png"))]
    return requests.post(url, data=fields, files=files, headers=get_headers(), timeout=TIMEOUT)


def _call_api(patch: Image.Image, output_dir: Path) -> Image.Image | None:
    """调用图像生成 API 填充品红区域。

    参数:
        patch: 带品红缺口的输入图。
        output_dir: 兼容参数，保留用于统一调用。
    返回:
        成功 → 填充后的图片；失败 → None。
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    fields = {
        "prompt": PROMPT,
        "requestId": f"fill-{int(time.time() * 1000)}",
        "model": MODEL,
        "aspectRatio": "1:1",
        "imageSize": "2K",
    }

    try:
        buffer = io.BytesIO()
        patch.save(buffer, format="PNG")
        resp = _api_request(f"{BASE_URL}{ENDPOINT}", fields, buffer.getvalue())

        resp.raise_for_status()

        ct = resp.headers.get("Content-Type", "")
        if ct.startswith("image/"):
            result_img = Image.open(io.BytesIO(resp.content)).convert("RGB")
            logger.info("模型填充 API 返回图片 %dx%d", result_img.width, result_img.height)
            return result_img

        # JSON 响应：可能包含文件路径或错误
        body = resp.json()
        if body.get("success") and body.get("file"):
            result_img = Image.open(body["file"]).convert("RGB")
            logger.info("模型填充 API 返回文件: %s", body["file"])
            return result_img

        logger.warning("模型填充 API 返回非图片: %s", json.dumps(body, ensure_ascii=False)[:200])
        return None

    except requests.HTTPError as exc:
        try:
            msg = exc.response.json().get("message", str(exc))
        except Exception:
            msg = str(exc)
        logger.warning("模型填充 API HTTP 错误: %s", msg)
        return None
    except requests.ConnectionError as exc:
        logger.warning("模型填充 API 连接失败: %s", exc)
        return None
    except Exception as exc:
        logger.warning("模型填充异常: %s", exc)
        return None


def _fill_full_crop_with_model(magenta_crop: Image.Image, output_dir: Path) -> Image.Image | None:
    """用完整品红裁切图生成完整补背景结果。

    参数:
        magenta_crop: 带品红缺口的完整方形裁切图。
        output_dir: 临时文件存放目录。
    返回值:
        成功时返回与 magenta_crop 同尺寸的补全图；失败时返回 None。
    """
    logger.info("完整裁切图尺寸 %dx%d，直接发送模型补全", magenta_crop.width, magenta_crop.height)
    result = _call_api(magenta_crop, output_dir)
    if result is None:
        logger.warning("完整裁切图模型填充失败")
        return None

    if result.size != magenta_crop.size:
        result = result.resize(magenta_crop.size, Image.Resampling.LANCZOS)

    repair_mask = _magenta_mask(magenta_crop)
    result = _remove_magenta_residue(result, repair_mask)
    logger.info("完整裁切图模型填充完成，采用整张返回图")
    return result


def _fill_patch_mask_with_model(
    magenta_crop: Image.Image,
    gaps: dict[str, int],
    output_dir: Path,
) -> Image.Image | None:
    """用局部 patch + 品红 mask 的旧方案补背景。

    参数:
        magenta_crop: 带品红缺口的完整方形裁切图。
        gaps: 各边缺口尺寸。
        output_dir: 临时文件存放目录。
    返回值:
        成功时返回补全后的完整裁切图；失败时返回 None。
    """
    # 旧方案仅作兜底：提取缺口小片，模型生成后只贴回品红区域。
    patch, patch_box = _extract_patch(magenta_crop, gaps)
    logger.info("兜底小片尺寸 %dx%d（裁切图中位置 %s）", patch.width, patch.height, patch_box)

    result = _call_api(patch, output_dir)
    if result is None:
        logger.warning("兜底小片模型填充失败")
        return None

    patch_w = patch_box[2] - patch_box[0]
    patch_h = patch_box[3] - patch_box[1]
    if result.size != (patch_w, patch_h):
        result = result.resize((patch_w, patch_h), Image.Resampling.LANCZOS)

    seam_delta = _estimate_seam_delta(patch, result)
    if seam_delta > 35:
        logger.warning("兜底小片填充边界颜色差较大，可能存在割裂感: %.1f", seam_delta)

    mask_image = _magenta_mask(patch)
    patched_crop = magenta_crop.copy()
    patched_crop.paste(result, (patch_box[0], patch_box[1]), mask_image)
    full_mask = Image.new("L", patched_crop.size, 0)
    full_mask.paste(mask_image, (patch_box[0], patch_box[1]))
    patched_crop = _remove_magenta_residue(patched_crop, full_mask)
    logger.info("兜底小片模型填充完成，已按品红 mask 贴回裁切图")
    return patched_crop


def fill_gaps_with_model(
    image: Image.Image,
    crop_box: tuple[int, int, int, int],
    output_dir: Path,
    fill_input_path: Path | None = None,
    fill_result_path: Path | None = None,
) -> Image.Image | None:
    """用生成模型填充 crop_box 越界产生的背景缺口。

    流程：裁切 → 缺口涂品红 → 完整裁切图调 API → 采用整张返回图。

    参数:
        image: 源图（RGB）。
        crop_box: 裁剪框，可超出源图边界。
        output_dir: 生图调试图片输出目录。
        fill_input_path: 品红缺口输入图保存路径，可为空。
        fill_result_path: 模型补齐结果图保存路径，可为空。
    返回:
        成功 → 填充后的完整裁切图（与 crop_box 尺寸一致）；
        失败 → None。
    """
    w, h = image.size
    gaps = _compute_gaps(crop_box, w, h)
    total_gap = sum(gaps.values())
    if total_gap == 0:
        logger.info("crop_box 未越界，无需填充")
        return image.crop(crop_box)

    logger.info("缺口: left=%d top=%d right=%d bottom=%d，启动模型填充",
                gaps["left"], gaps["top"], gaps["right"], gaps["bottom"])

    # 1. 构造带品红缺口的裁切图
    magenta_crop, gaps = _build_magenta_crop(image, crop_box)
    if fill_input_path is not None:
        fill_input_path.parent.mkdir(parents=True, exist_ok=True)
        magenta_crop.save(fill_input_path, quality=95)

    # 2. 默认采用完整裁切图返回结果，避免局部 mask 硬贴产生接缝。
    result = _fill_full_crop_with_model(magenta_crop, output_dir)
    if result is not None:
        if fill_result_path is not None:
            fill_result_path.parent.mkdir(parents=True, exist_ok=True)
            result.save(fill_result_path, quality=95)
        return result

    # 3. 完整图调用失败时，保留旧 patch/mask 方案作为兜底。
    logger.warning("切换到兜底小片补全方案")
    result = _fill_patch_mask_with_model(magenta_crop, gaps, output_dir)
    if result is not None and fill_result_path is not None:
        fill_result_path.parent.mkdir(parents=True, exist_ok=True)
        result.save(fill_result_path, quality=95)
    return result
