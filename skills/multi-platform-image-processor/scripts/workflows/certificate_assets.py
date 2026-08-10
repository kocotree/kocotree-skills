from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any

from common.bartender_exporter import export_bartender_image
from common.certificate_composer import compose_certificate, compose_hangtag
from common.delivery_quality_audit import audit_business_images
from common.product_matcher import extract_size, select_bartender_file
from common.size_table_extractor import CropBox, compose_size_image, extract_size_table
from common.workflow_report import add_report_item

from .business_support import parse_box


logger = logging.getLogger(__name__)


def _resolve_size_source(content_root: Path, value: str) -> Path:
    """解析用户或 Agent 确认的尺码表详情图。"""
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (content_root / path).resolve()


def generate_business_images(
    args: Any,
    product_code: str,
    product_name: str,
    product_root: Path,
    content_root: Path,
    certificate_root: Path,
    report: dict[str, Any],
) -> bool:
    """生成合格证图、吊牌图和尺码图。

    参数：
        args：包含 Agent 内部视觉定位结果的入口参数。
        product_code：已确认的产品货号。
        product_name：用于复核候选的产品名称。
        product_root：业务图片输出产品目录。
        content_root：详情图相对路径解析根目录。
        certificate_root：BarTender 文件目录。
        report：业务顶层报告。
    返回值：
        图片生成和自动质检通过时返回 True。
    """
    match = select_bartender_file(
        certificate_root,
        product_code,
        product_name,
    )
    report["BarTender导出"]["候选文件"] = [str(path) for path in match.candidates]
    report["BarTender导出"]["选择说明"] = match.reason
    if match.selected is None:
        add_report_item(report, "失败项", "BarTender 文件匹配失败", 原因=match.reason)
        return False
    selected = Path(match.selected)
    report["BarTender导出"]["选中文件"] = str(selected)
    report["BarTender导出"]["代表颜色"] = "按候选自然顺序选择"
    report["BarTender导出"]["代表尺码"] = extract_size(selected.stem)
    size_source_value = getattr(args, "size_table_source", "")
    size_box_value = getattr(args, "size_table_box", "")
    if not size_source_value or not size_box_value:
        add_report_item(report, "失败项", "缺少实际尺码表来源或完整裁切坐标")
        report["Agent复核建议"].append(
            {
                "任务名称": "选择实际尺码表",
                "图片路径": [str(content_root)],
                "原因": "需要排除尺码快选和试穿表，并确认标题、灰框和完整底行边界",
            }
        )
        return False
    size_source = _resolve_size_source(content_root, size_source_value)
    if not size_source.is_file():
        add_report_item(report, "失败项", "尺码表详情图不存在", 文件=str(size_source))
        return False
    size_box = CropBox(*parse_box(size_box_value, "尺码表区域"))
    with tempfile.TemporaryDirectory(prefix="kocotree-certificate-") as temp_dir_value:
        temp_dir = Path(temp_dir_value)
        exported = export_bartender_image(selected, temp_dir / "bartender-export.png")
        report["BarTender导出"]["源文件保护"] = "通过"
        table = extract_size_table(size_source, temp_dir / "size-table.png", size_box)
        try:
            certificate_path = compose_certificate(
                exported,
                product_root / "合格证" / "合格证图.jpg",
            )
            hangtag_path = compose_hangtag(
                exported,
                product_root / "吊牌图" / "吊牌图.jpg",
            )
            report["业务图片"]["合格证图"] = {"状态": "成功", "路径": str(certificate_path)}
            report["业务图片"]["吊牌图"] = {"状态": "成功", "路径": str(hangtag_path)}
            size_path = compose_size_image(
                exported,
                table,
                product_root / "尺码图" / "尺码图.jpg",
            )
            report["业务图片"]["尺码图"] = {"状态": "成功", "路径": str(size_path)}
        except Exception as exc:
            add_report_item(report, "失败项", "业务图片合成失败", 错误=str(exc))
            return False
    passed = audit_business_images(product_root, report, require_all=True)
    if not getattr(args, "visual_review_approved", False):
        report["Agent复核建议"].append(
            {
                "任务名称": "复核业务图片排版与清晰度",
                "图片路径": [
                    item["路径"] for item in report["业务图片"].values()
                    if isinstance(item, dict) and item.get("路径")
                ],
                "原因": "确认尺码表完整清晰、三张业务图片排版正常且非目标内容未受影响",
            }
        )
    return passed
