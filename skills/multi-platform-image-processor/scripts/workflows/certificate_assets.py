from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any

from common.bartender_exporter import export_bartender_image
from common.certificate_composer import compose_certificate, compose_hangtag
from common.delivery_quality_audit import audit_business_images
from common.font_assets import load_font_assets
from common.nas_paths import require_accessible_directory, to_unc_path
from common.product_info_reader import ProductInfoRecord, extract_chinese_material, find_product_info
from common.product_matcher import extract_size, select_bartender_file
from common.settings import resolve_business_paths
from common.size_image_composer import compose_size_image
from common.size_table_extractor import CropBox, extract_size_table
from common.workflow_report import add_report_item, new_workflow_report, write_workflow_report

from .business_support import default_business_report_path, parse_box, parse_point, product_match_to_dict


logger = logging.getLogger(__name__)


def _resolve_size_source(content_root: Path, value: str) -> Path:
    """解析用户或 Agent 确认的尺码表详情图。"""
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (content_root / path).resolve()


def generate_business_images(
    args: Any,
    record: ProductInfoRecord,
    product_root: Path,
    content_root: Path,
    certificate_root: Path,
    report: dict[str, Any],
    generate_all: bool,
) -> bool:
    """生成完整业务图片或仅生成必需尺码图。

    参数：
        args：统一入口参数。
        record：唯一匹配的产品信息记录。
        product_root：业务图片输出产品目录。
        content_root：详情图相对路径解析根目录。
        certificate_root：BarTender 文件目录。
        report：业务顶层报告。
        generate_all：True 生成三张图片，False 只生成尺码图。
    返回值：
        图片生成和自动质检通过时返回 True。
    """
    match = select_bartender_file(
        certificate_root,
        args.product_code,
        args.product_name,
        args.color,
    )
    report["BarTender导出"]["候选文件"] = [str(path) for path in match.candidates]
    report["BarTender导出"]["选择说明"] = match.reason
    if match.selected is None:
        add_report_item(report, "失败项", "BarTender 文件匹配失败", 原因=match.reason)
        return False
    selected = Path(match.selected)
    report["BarTender导出"]["选中文件"] = str(selected)
    report["BarTender导出"]["代表颜色"] = args.color or "按候选自然顺序选择"
    report["BarTender导出"]["代表尺码"] = extract_size(selected.stem)
    if not args.size_table_source or not args.size_table_box:
        add_report_item(report, "失败项", "缺少实际尺码表来源或完整裁切坐标")
        report["Agent复核建议"].append(
            {
                "任务名称": "选择实际尺码表",
                "图片路径": [str(content_root)],
                "原因": "需要排除尺码快选和试穿表，并确认标题、灰框和完整底行边界",
            }
        )
        return False
    size_source = _resolve_size_source(content_root, args.size_table_source)
    if not size_source.is_file():
        add_report_item(report, "失败项", "尺码表详情图不存在", 文件=str(size_source))
        return False
    size_box = CropBox(*parse_box(args.size_table_box, "尺码表区域"))
    with tempfile.TemporaryDirectory(prefix="kocotree-certificate-") as temp_dir_value:
        temp_dir = Path(temp_dir_value)
        exported = export_bartender_image(selected, temp_dir / "bartender-export.png")
        report["BarTender导出"]["源文件保护"] = "通过"
        table = extract_size_table(size_source, temp_dir / "size-table.png", size_box)
        try:
            if generate_all:
                fabric = extract_chinese_material(record.get("中文面料", "")) if args.include_certificate_fabric else ""
                if args.include_certificate_fabric and not fabric:
                    raise RuntimeError("产品信息 Excel 缺少可用的中文面料")
                anchor = None
                font = None
                if fabric:
                    if not args.fabric_anchor:
                        raise RuntimeError("合格证加入面料时缺少“等级”下方锚点")
                    anchor = parse_point(args.fabric_anchor, "合格证面料锚点")
                    font = load_font_assets()["方正兰亭中黑"]
                certificate_path = compose_certificate(
                    exported,
                    product_root / "合格证" / "合格证图.jpg",
                    fabric,
                    anchor,
                    font,
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
    passed = audit_business_images(product_root, report, require_all=generate_all)
    if not args.visual_review_approved:
        report["Agent复核建议"].append(
            {
                "任务名称": "复核业务图片排版与清晰度",
                "图片路径": [
                    item["路径"] for item in report["业务图片"].values()
                    if isinstance(item, dict) and item.get("路径")
                ],
                "原因": "确认尺码表完整、合格证面料位置及非目标内容未受影响",
            }
        )
    return passed


def run_certificate_workflow(args: Any) -> int:
    """执行合格证相关图片专项。

    参数：
        args：统一入口解析后的命令行参数。
    返回值：
        成功返回 0，存在失败项返回 1。
    """
    source = Path(args.source).expanduser().resolve()
    product_root = Path(args.output).expanduser().resolve() if args.output else (
        source.parent if source.name == "数据包" else source
    )
    report = new_workflow_report("certificate", source, product_root)
    report_path = Path(args.report).expanduser().resolve() if args.report else default_business_report_path("certificate", args.product_code)
    try:
        business_paths = resolve_business_paths(args.nas_root, args.product_info_root, args.certificate_root)
        product_info_root = require_accessible_directory(
            to_unc_path(business_paths.product_info_root),
            "产品信息目录",
        )
        certificate_root = require_accessible_directory(
            to_unc_path(business_paths.certificate_root),
            "BarTender 合格证目录",
        )
        match = find_product_info(product_info_root, args.product_code, args.product_name)
        report["产品匹配"] = product_match_to_dict(
            match.selected if isinstance(match.selected, ProductInfoRecord) else None,
            match.candidates,
            match.reason,
        )
        if match.selected is None:
            raise RuntimeError(match.reason)
        record = match.selected
        assert isinstance(record, ProductInfoRecord)
        generate_business_images(
            args,
            record,
            product_root,
            source,
            certificate_root,
            report,
            generate_all=True,
        )
    except Exception as exc:
        add_report_item(report, "失败项", "合格证专项执行失败", 错误=str(exc))
    write_workflow_report(report, report_path)
    return 0 if not report["失败项"] else 1
