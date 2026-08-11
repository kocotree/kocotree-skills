from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from common import (
    add_failure,
    add_platform_result,
    add_warning,
    build_platform_directory_names,
    copy_template_empty_dirs,
    ensure_dir,
    new_report,
    全部平台,
    平台模板目录名,
)
from common.quality_audit import run_quality_audit
from common.run_logging import (
    close_run_file_logging,
    configure_run_file_logging,
    default_run_log_path,
    prune_run_logs,
    report_artifact_prefix,
)
from common.scan_source_pack import scan_source_pack
from common.source_pack_validator import validate_source_pack
from common.write_report import write_report
from platforms.cbme import derive as derive_cbme
from platforms.fengxiang_aikucun import derive as derive_fengxiang_aikucun
from platforms.jd import derive as derive_jd
from platforms.offsite import derive as derive_offsite
from platforms.tmall import build as build_tmall
from platforms.vip import derive as derive_vip

logger = logging.getLogger(__name__)


def default_report_path(output: Path) -> Path:
    """生成平台处理默认报告路径。"""
    safe_name = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in output.name).strip("_")
    if not safe_name:
        safe_name = "output"
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path(__file__).resolve().parents[1] / "output" / "report" / f"{safe_name}-{timestamp}-report.json"


def prune_report_files(report_dir: Path, keep: int = 100) -> None:
    """保留最近的主报告和对应逐图明细。"""
    reports = sorted(
        report_dir.glob("*-report.json"),
        key=lambda path: (path.stat().st_mtime, path.name),
        reverse=True,
    )
    for old_report in reports[keep:]:
        detail_path = old_report.with_name(f"{report_artifact_prefix(old_report)}-image-records.jsonl")
        old_report.unlink(missing_ok=True)
        detail_path.unlink(missing_ok=True)


def default_template_path() -> Path:
    """返回 Skill 内置平台模板目录。"""
    return Path(__file__).resolve().parents[2] / "template"


def default_output_path() -> Path:
    """返回跨平台兼容的默认输出目录。"""
    desktop = Path("E:/桌面")
    if not desktop.exists():
        desktop = Path.home() / "Desktop"
    return desktop / "multi-platform-image-processor" / "output"


def resolve_source_and_output(source: Path, output_root: Path) -> tuple[Path, Path, str]:
    """解析单产品标准数据包和带时间戳输出目录。"""
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    if source.name == "数据包":
        product_name = source.parent.name
        return source, output_root / f"{product_name}_{timestamp}", product_name
    data_pack = source / "数据包"
    if data_pack.is_dir():
        return data_pack, output_root / f"{source.name}_{timestamp}", source.name
    return source, output_root / timestamp, ""


def run_single(
    source_arg: Path,
    template: Path,
    output_arg: Path,
    report_override: Path | None = None,
    product_code: str = "",
    product_name: str = "",
    detail_plan: Path | None = None,
) -> tuple[int, Path, Path]:
    """处理单个产品并生成六平台图片与报告。

    参数：
        source_arg：数据包目录或产品目录。
        template：平台模板路径。
        output_arg：输出根目录。
        report_override：可选的主报告路径。
        product_code：Excel 确认的产品货号，用于构造京东目录名。
        product_name：Excel 确认的产品名称，用于构造京东目录名。
        detail_plan：Agent 视觉检查生成的详情模块计划路径。
    返回值：
        退出码、实际输出目录和主报告路径。
    """
    source, output, source_product_name = resolve_source_and_output(source_arg, output_arg)
    effective_product_name = product_name.strip() or source_product_name
    report_path = report_override or default_report_path(output)
    run_id = report_artifact_prefix(report_path)
    display_product = effective_product_name or source.parent.name or source.name
    log_path = configure_run_file_logging(default_run_log_path(report_path), run_id, display_product)
    report = new_report(source, template, output, "all")
    report["处理配置"]["运行ID"] = run_id
    report["追溯文件"]["运行日志"] = str(log_path)
    if effective_product_name:
        report["处理配置"]["产品名"] = effective_product_name
        report["处理配置"]["源参数目录"] = str(source_arg)
        report["处理配置"]["输出根目录"] = str(output_arg)
    if product_name.strip():
        logger.info(
            "平台目录使用已确认产品身份 code=%s name=%s",
            product_code,
            effective_product_name,
        )
    else:
        logger.warning(
            "未提供确认产品名称，平台目录使用源目录名称 name=%s",
            effective_product_name,
        )
    logger.info("六平台任务开始 source=%r output=%r", str(source), str(output))
    try:
        if not source.exists():
            add_failure(report, "源数据包目录不存在", 源目录=str(source))
            write_report(report, report_path)
            prune_report_files(report_path.parent)
            return 2, output, report_path

        validation = validate_source_pack(source)
        report["输入包检测"] = validation
        report["素材扫描"] = scan_source_pack(source)
        for warning in validation["警告"]:
            add_warning(report, warning["信息"], **{key: value for key, value in warning.items() if key != "信息"})
        if not validation["通过"]:
            for problem in validation["问题"]:
                add_failure(
                    report,
                    "输入包检测失败",
                    问题=problem["信息"],
                    **{key: value for key, value in problem.items() if key != "信息"},
                )
            write_report(report, report_path)
            prune_report_files(report_path.parent)
            return 2, output, report_path

        ensure_dir(output)
        directory_names = build_platform_directory_names(product_code, effective_product_name)
        platform_directories = {
            key: output / directory_names[key]
            for key in 全部平台
        }
        for key in 全部平台:
            copy_template_empty_dirs(template, 平台模板目录名[key], platform_directories[key])

        tmall_dir = build_tmall(source, output, report, detail_plan)
        derive_cbme(source, tmall_dir, output, report)
        derive_jd(source, tmall_dir, platform_directories["jd"], report)
        derive_vip(source, tmall_dir, output, report)
        derive_fengxiang_aikucun(source, tmall_dir, output, report)
        derive_offsite(source, template, output, report)

        run_quality_audit(output, 全部平台, report, platform_directories)
        for key in 全部平台:
            add_platform_result(report, directory_names[key], platform_directories[key])
        write_report(report, report_path)
        prune_report_files(report_path.parent)
        exit_code = 0 if not report["失败项"] else 1
        logger.info("平台任务结束 output=%r report=%r code=%d", str(output), str(report_path), exit_code)
        return exit_code, output, report_path
    finally:
        prune_run_logs(log_path.parent)
        close_run_file_logging()
