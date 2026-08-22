from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any

from common.bartender_exporter import export_bartender_image
from common.certificate_composer import compose_certificate, compose_hangtag
from common.delivery_quality_audit import audit_business_images
from common.font_assets import load_font_assets
from common.product_matcher import extract_size, select_bartender_file
from common.settings import skill_root
from common.size_table_extractor import (
    CropBox,
    compose_size_image,
    extract_size_table,
)
from common.utils import add_report_item

from .business_support import parse_box, parse_point

logger = logging.getLogger(__name__)


def _resolve_size_source(content_root: Path, value: str) -> Path:
    """解析用户或 Agent 确认的尺码表详情图。"""
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (content_root / path).resolve()


def _resolve_certificate_fabric_settings(
    context: dict[str, Any],
    fabric_text: str,
) -> tuple[str, tuple[int, int] | None, int]:
    """根据原合格证面料完整性决定是否补充 Excel 面料。

    参数：
        context：Agent 内部视觉定位结果。
        fabric_text：产品信息 Excel 中的中文面料原文。
    返回值：
        待新增的面料文字、可选面料锚点和字号；原合格证信息完整时文字为空。
    """
    material_complete = context.get("合格证面料完整")
    if not isinstance(material_complete, bool):
        raise ValueError("缺少原合格证面料完整性结论")
    if material_complete:
        return "", None, 0

    anchor_value = context.get("合格证面料锚点")
    font_size = int(context.get("合格证面料字号", 0))
    if not anchor_value or font_size <= 0:
        raise ValueError("缺少合格证等级字段下方面料锚点或字号")
    return fabric_text, parse_point(anchor_value, "合格证面料锚点"), font_size


def generate_business_images(
    context: dict[str, Any],
    product_name: str,
    representative_color: str,
    fabric_text: str,
    product_root: Path,
    content_root: Path,
    certificate_root: Path,
    report: dict[str, Any],
) -> bool:
    """生成合格证图、吊牌图和尺码图。

    参数：
        context：Agent 内部视觉定位结果。
        product_name：产品信息 Excel 中的正式产品名称。
        representative_color：产品信息 Excel 首个颜色或规格对应的代表颜色。
        fabric_text：产品信息 Excel 中的中文面料原文。
        product_root：业务图片输出产品目录。
        content_root：详情图相对路径解析根目录。
        certificate_root：BarTender 文件目录。
        report：完整处理报告。
    返回值：
        图片生成和自动质检通过时返回 True。
    """
    match = select_bartender_file(
        certificate_root,
        product_name,
        representative_color,
    )
    report["BarTender导出"]["候选文件"] = [str(path) for path in match.candidates]
    report["BarTender导出"]["选择说明"] = match.reason
    if match.selected is None:
        add_report_item(report, "失败项", "BarTender 文件匹配失败", 原因=match.reason)
        return False
    selected = Path(match.selected)
    report["BarTender导出"]["选中文件"] = str(selected)
    report["BarTender导出"]["代表颜色"] = representative_color
    report["BarTender导出"]["代表尺码"] = extract_size(selected.stem)
    size_source_value = str(context.get("尺码表图片", "")).strip()
    size_box_value = context.get("尺码表区域")
    size_unit_text = str(context.get("尺码单位文字", "")).strip()
    if not size_source_value or not size_box_value or not size_unit_text:
        add_report_item(report, "失败项", "缺少实际尺码表、实际尺码单位或完整裁切坐标")
        report["Agent复核建议"].append(
            {
                "任务名称": "选择实际尺码表",
                "图片路径": [str(content_root)],
                "原因": "需要排除尺码快选和试穿表，并确认实际单位、标题、灰框和完整底行边界",
            }
        )
        return False
    try:
        certificate_fabric_text, fabric_anchor, fabric_font_size = (
            _resolve_certificate_fabric_settings(context, fabric_text)
        )
    except (TypeError, ValueError) as exc:
        add_report_item(report, "失败项", "合格证面料处理信息不完整", 原因=str(exc))
        report["Agent复核建议"].append(
            {
                "任务名称": "确认原合格证面料完整性",
                "图片路径": [str(selected)],
                "原因": "需要确认原合格证面料是否完整；需要补充时定位等级下方锚点和字号",
            }
        )
        return False
    fabric_fonts = load_font_assets() if certificate_fabric_text else None
    dealer_address_image = skill_root() / "assets" / "合格证-经销商地址.jpg"
    original_material_complete = bool(context["合格证面料完整"])
    report["BarTender导出"]["原合格证面料完整"] = original_material_complete
    if fabric_anchor is not None:
        report["BarTender导出"]["合格证面料锚点"] = list(fabric_anchor)
        report["BarTender导出"]["合格证面料字号"] = fabric_font_size
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
                product_root / "唯品会" / "合格证.jpg",
                dealer_address_image,
                fabric_text=certificate_fabric_text,
                fabric_anchor=fabric_anchor,
                fabric_fonts=fabric_fonts,
                font_size=fabric_font_size,
            )
            hangtag_path = compose_hangtag(
                exported,
                product_root / "天猫通用版" / "吊牌图.jpg",
            )
            report["业务图片"]["合格证图"] = {
                "状态": "成功",
                "路径": str(certificate_path),
                "面料处理": (
                    "保留原合格证面料"
                    if original_material_complete
                    else "补充Excel中文面料"
                ),
                "经销商地址图片": str(dealer_address_image),
            }
            report["业务图片"]["吊牌图"] = {"状态": "成功", "路径": str(hangtag_path)}
            size_path = compose_size_image(
                exported,
                table,
                size_unit_text,
                product_root / "蜂享家＋爱库存" / "尺码图" / "尺码图.jpg",
                fabric_fonts,
            )
            report["业务图片"]["尺码图"] = {
                "状态": "成功",
                "路径": str(size_path),
                "尺码单位来源": str(size_source),
                "尺码单位": size_unit_text,
            }
        except Exception as exc:
            add_report_item(report, "失败项", "业务图片合成失败", 错误=str(exc))
            return False
    passed = audit_business_images(product_root, report)
    report["Agent复核建议"].append(
        {
            "任务名称": "复核业务图片排版与清晰度",
            "图片路径": [
                item["路径"] for item in report["业务图片"].values()
                if isinstance(item, dict) and item.get("路径")
            ],
            "原因": "确认尺码表和右上角单位完整清晰、三张业务图片排版正常且非目标内容未受影响",
        }
    )
    return passed
