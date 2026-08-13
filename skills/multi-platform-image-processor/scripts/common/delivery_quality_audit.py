from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from PIL import Image

from .utils import add_report_item


logger = logging.getLogger(__name__)
EXPECTED_ASSETS = {
    "合格证图": ("合格证/合格证图.jpg", (750, 1600)),
    "吊牌图": ("吊牌图/吊牌图.jpg", (800, 800)),
    "尺码图": ("尺码图/尺码图.jpg", (800, 800)),
}
BUSINESS_IMAGE_MAX_BYTES = 500 * 1024


def _corners_are_white(image: Image.Image, threshold: int = 242) -> bool:
    rgb = image.convert("RGB")
    corners = [
        rgb.getpixel((0, 0)),
        rgb.getpixel((rgb.width - 1, 0)),
        rgb.getpixel((0, rgb.height - 1)),
        rgb.getpixel((rgb.width - 1, rgb.height - 1)),
    ]
    return all(min(pixel) >= threshold for pixel in corners)


def audit_business_images(
    product_root: Path,
    report: dict[str, Any],
) -> bool:
    """检查业务图片存在性、尺寸、格式和白底。

    参数：
        product_root：业务图片所在产品目录。
        report：需要记录质检结果的完整报告。
    返回值：
        全部必需自动检查通过时返回 True。
    """
    passed = True
    for name, (relative, expected_size) in EXPECTED_ASSETS.items():
        path = product_root / Path(relative)
        item_passed = True
        if not path.is_file():
            add_report_item(report, "失败项", f"缺少{name}", 文件=str(path))
            passed = False
            report["业务图片"].setdefault(name, {})["自动质检"] = "存在问题"
            continue
        try:
            if path.stat().st_size > BUSINESS_IMAGE_MAX_BYTES:
                add_report_item(
                    report,
                    "失败项",
                    f"{name}文件大小超过500KB",
                    文件=str(path),
                    实际KB=round(path.stat().st_size / 1024, 2),
                )
                passed = False
                item_passed = False
            with Image.open(path) as image:
                if image.size != expected_size:
                    add_report_item(
                        report,
                        "失败项",
                        f"{name}尺寸不合格",
                        文件=str(path),
                        实际尺寸=list(image.size),
                        期望尺寸=list(expected_size),
                    )
                    passed = False
                    item_passed = False
                if image.format != "JPEG":
                    add_report_item(report, "失败项", f"{name}格式不是 JPG", 文件=str(path))
                    passed = False
                    item_passed = False
                if not _corners_are_white(image):
                    add_report_item(report, "失败项", f"{name}画布四角不是白底", 文件=str(path))
                    passed = False
                    item_passed = False
        except Exception as exc:
            add_report_item(report, "失败项", f"{name}无法读取", 文件=str(path), 错误=str(exc))
            passed = False
            item_passed = False
        report["业务图片"].setdefault(name, {})["自动质检"] = "通过" if item_passed else "存在问题"
    logger.info("业务图片自动质检完成 root=%r passed=%s", str(product_root), passed)
    return passed
