from __future__ import annotations

import logging
import os
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
from common.run_logging import (
    close_run_file_logging,
    configure_run_file_logging,
)
from common.run_workspace import (
    TEXT_REMOVAL_CANDIDATES_ENV,
    create_run_workspace,
    prune_internal_runs,
    publish_delivery,
    replace_report_path_prefix,
)
from common.utils import add_report_item, new_report
from common.write_report import write_report

from .business_support import load_plan, product_match_to_dict
from .certificate_assets import generate_business_images
from .material_correction import apply_material_plan
from .platform_processing import (
    default_output_path,
    default_template_path,
    run_platform_processing,
)

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
    workspace = create_run_workspace(product_code)
    prune_internal_runs(protected=workspace.root)
    report_path = workspace.report_path
    template = default_template_path()
    report = new_report(source, template, output_root)
    run_id = workspace.run_id
    display_product = product_name or product_code or source.parent.name or source.name
    log_path = configure_run_file_logging(workspace.log_path, run_id, display_product)
    report["处理配置"]["运行ID"] = run_id
    report["处理配置"]["产品名"] = display_product
    report["追溯文件"]["运行目录"] = str(workspace.root)
    report["追溯文件"]["内部报告"] = str(report_path)
    report["追溯文件"]["运行日志"] = str(log_path)
    previous_candidates_dir = os.environ.get(TEXT_REMOVAL_CANDIDATES_ENV)
    os.environ[TEXT_REMOVAL_CANDIDATES_ENV] = str(workspace.candidates_dir)
    context_value = getattr(args, "context", "")
    context = load_plan(Path(context_value).expanduser().resolve()) if context_value else {}
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
        plan_value = str(context.get("面料计划", "")).strip()
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

            detail_plan_value = str(context.get("详情计划", "")).strip()
            detail_plan = Path(detail_plan_value).expanduser().resolve() if detail_plan_value else None
            platform_code, product_output = run_platform_processing(
                source,
                template,
                workspace.staging_root,
                report,
                product_code=confirmed_product_code,
                product_name=confirmed_product_name,
                detail_plan=detail_plan,
                detail_overrides=detail_overrides,
                color_name_plan=context.get("颜色命名"),
                delivery_timestamp=workspace.timestamp,
            )
        if platform_code != 0:
            logger.warning("平台处理存在失败项 code=%d", platform_code)

        business_ok = generate_business_images(
            context=context,
            product_name=confirmed_product_name,
            representative_color=representative_color,
            fabric_text=expected,
            product_root=product_output,
            content_root=source,
            certificate_root=certificate_root,
            report=report,
        )
        if not business_ok and not report["失败项"]:
            raise RuntimeError("业务图片生成未通过")
        if platform_code != 0 and not report["失败项"]:
            raise RuntimeError("六平台处理未通过")
        if not report["失败项"]:
            staging_product = product_output
            final_output = publish_delivery(staging_product, output_root)
            report = replace_report_path_prefix(report, staging_product, final_output)
            report["处理配置"]["输出目录"] = str(final_output)
            report["处理配置"]["输出根目录"] = str(output_root)
            report["路径"]["最终输出"] = str(final_output)
        else:
            report["路径"]["最终输出"] = ""
    except Exception as exc:
        report["路径"]["最终输出"] = ""
        add_report_item(report, "失败项", "完整流程执行失败", 错误=str(exc))
    finally:
        try:
            write_report(report, report_path)
        finally:
            if previous_candidates_dir is None:
                os.environ.pop(TEXT_REMOVAL_CANDIDATES_ENV, None)
            else:
                os.environ[TEXT_REMOVAL_CANDIDATES_ENV] = previous_candidates_dir
            close_run_file_logging()
            prune_internal_runs(protected=workspace.root)
    return 0 if not report["失败项"] else 1
