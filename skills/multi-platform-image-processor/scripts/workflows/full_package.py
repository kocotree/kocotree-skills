from __future__ import annotations

import json
import logging
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from common.nas_paths import require_accessible_directory, to_unc_path
from common.product_info_reader import (
    ProductInfoRecord,
    extract_chinese_material,
    extract_representative_color,
    find_product_info,
)
from common.product_matcher import infer_product_code
from common.settings import resolve_business_paths
from common.workflow_report import (
    add_report_item,
    merge_platform_report,
    new_workflow_report,
    write_workflow_report,
)

from .business_support import default_business_report_path, product_match_to_dict
from .certificate_assets import generate_business_images
from .material_correction import apply_material_plan
from .platform_processing import default_output_path, default_template_path, run_single

logger = logging.getLogger(__name__)


def run_full_workflow(args: Any) -> int:
    """执行面料、六平台和业务图片完整流程。

    参数：
        args：统一入口解析后的命令行参数。
    返回值：
        完成返回 0，存在失败项返回 1。
    """
    source = Path(args.source).expanduser().resolve()
    product_code = args.product_code.strip() or infer_product_code(source)
    product_name = args.product_name.strip()
    output_root = Path(args.output).expanduser().resolve() if args.output else default_output_path()
    report = new_workflow_report("完整流程", source, output_root)
    report_path = default_business_report_path(product_code)
    try:
        if not product_code:
            raise RuntimeError("无法从产品目录可靠识别货号，请提供 --product-code")
        business_paths = resolve_business_paths()
        product_info_root = require_accessible_directory(
            to_unc_path(business_paths.product_info_root),
            "产品信息目录",
        )
        certificate_root = require_accessible_directory(
            to_unc_path(business_paths.certificate_root),
            "BarTender 合格证目录",
        )
        match = find_product_info(product_info_root, product_code, product_name)
        report["产品匹配"] = product_match_to_dict(
            match.selected if isinstance(match.selected, ProductInfoRecord) else None,
            match.candidates,
            match.reason,
        )
        if match.selected is None:
            raise RuntimeError(match.reason)
        record = match.selected
        assert isinstance(record, ProductInfoRecord)
        confirmed_product_code = str(record.get("产品货号", "")).strip() or product_code
        confirmed_product_name = str(record.get("产品名称", "")).strip() or product_name
        if not confirmed_product_name:
            raise RuntimeError("产品信息 Excel 缺少产品名称")
        expected = extract_chinese_material(record.get("中文面料", ""))
        if not expected:
            raise RuntimeError("产品信息 Excel 缺少中文面料")
        representative_color = extract_representative_color(record)
        if not representative_color:
            raise RuntimeError("产品信息 Excel 缺少可识别的代表颜色或规格")
        report["面料检查"]["Excel中文原文"] = expected
        report["产品匹配"]["代表颜色"] = representative_color
        report["路径"]["源UNC路径"] = str(to_unc_path(source))
        plan_value = getattr(args, "material_plan", "")
        plan_path = Path(plan_value).expanduser().resolve() if plan_value else None
        with TemporaryDirectory(prefix="kocotree-material-") as staging_value:
            detail_overrides = apply_material_plan(
                source,
                expected,
                plan_path,
                Path(staging_value),
                report,
            )
            if detail_overrides is None:
                raise RuntimeError("详情页面料检查未完成，平台派生已停止")

            platform_report_path = report_path.with_name(f"{report_path.stem}-platform-report.json")
            template = default_template_path()
            detail_plan_value = getattr(args, "detail_plan", "")
            detail_plan = Path(detail_plan_value).expanduser().resolve() if detail_plan_value else None
            platform_code, product_output, actual_platform_report = run_single(
                source,
                template,
                output_root,
                platform_report_path,
                product_code=confirmed_product_code,
                product_name=confirmed_product_name,
                detail_plan=detail_plan,
                detail_overrides=detail_overrides,
            )
        platform_report = json.loads(actual_platform_report.read_text(encoding="utf-8"))
        merge_platform_report(report, platform_report, actual_platform_report)
        report["路径"]["最终输出"] = str(product_output)
        if platform_code != 0:
            add_report_item(report, "失败项", "平台处理引擎存在失败项", 退出码=platform_code)

        generate_business_images(
            args=args,
            product_name=confirmed_product_name,
            representative_color=representative_color,
            fabric_text=expected,
            product_root=product_output,
            content_root=source,
            certificate_root=certificate_root,
            report=report,
        )
    except Exception as exc:
        add_report_item(report, "失败项", "完整流程执行失败", 错误=str(exc))
    write_workflow_report(report, report_path)
    return 0 if not report["失败项"] else 1
