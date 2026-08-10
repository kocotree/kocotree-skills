from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from common import (
    全部平台,
    平台目录名,
    add_failure,
    add_platform_result,
    add_warning,
    copy_template_empty_dirs,
    ensure_dir,
    new_report,
    resolve_path,
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


def detect_batch(source: Path) -> list[Path]:
    """返回批处理总目录下的产品目录。"""
    if source.name == "数据包" or (source / "数据包").is_dir():
        return []
    return sorted(
        child for child in source.iterdir()
        if child.is_dir() and (child / "数据包").is_dir()
    )


def run_single(
    source_arg: Path,
    template: Path,
    output_arg: Path,
    platform: str,
    report_override: Path | None = None,
) -> tuple[int, Path, Path]:
    """处理单个产品并生成平台图片与报告。

    参数：
        source_arg：数据包目录或产品目录。
        template：平台模板路径。
        output_arg：输出根目录。
        platform：目标平台参数。
        report_override：可选的主报告路径。
    返回值：
        退出码、实际输出目录和主报告路径。
    """
    source, output, product_name = resolve_source_and_output(source_arg, output_arg)
    report_path = report_override or default_report_path(output)
    run_id = report_artifact_prefix(report_path)
    display_product = product_name or source.parent.name or source.name
    log_path = configure_run_file_logging(default_run_log_path(report_path), run_id, display_product)
    report = new_report(source, template, output, platform)
    report["处理配置"]["运行ID"] = run_id
    report["追溯文件"]["运行日志"] = str(log_path)
    if product_name:
        report["处理配置"]["产品名"] = product_name
        report["处理配置"]["源参数目录"] = str(source_arg)
        report["处理配置"]["输出根目录"] = str(output_arg)
    logger.info("平台任务开始 source=%r output=%r platform=%s", str(source), str(output), platform)
    try:
        if not source.exists():
            add_failure(report, "源数据包目录不存在", 源目录=str(source))
            write_report(report, report_path)
            prune_report_files(report_path.parent)
            return 2, output, report_path

        validation_assets_dir = report_path.parent / f"{report_path.stem}-assets" / "透明图问题"
        validation = validate_source_pack(source, validation_assets_dir)
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
        selected = 全部平台 if platform == "all" else [platform]
        tmall_needed = "tmall" in selected or any(
            item in selected for item in ["cbme", "jd", "vip", "fengxiang-aikucun"]
        )
        for key in selected:
            copy_template_empty_dirs(template, 平台目录名[key], output / 平台目录名[key])

        tmall_dir = output / 平台目录名["tmall"]
        if tmall_needed:
            tmall_dir = build_tmall(source, output, report)
        for key in selected:
            if key == "tmall":
                continue
            if key == "cbme":
                derive_cbme(source, tmall_dir, output, report)
            elif key == "jd":
                derive_jd(source, tmall_dir, output, report)
            elif key == "vip":
                derive_vip(source, tmall_dir, output, report)
            elif key == "fengxiang-aikucun":
                derive_fengxiang_aikucun(source, tmall_dir, output, report)
            elif key == "offsite":
                derive_offsite(source, template, output, report)

        audit_platforms = selected.copy()
        if tmall_needed and "tmall" not in audit_platforms:
            audit_platforms.insert(0, "tmall")
        run_quality_audit(output, audit_platforms, report)
        for key in audit_platforms:
            add_platform_result(report, 平台目录名[key], output / 平台目录名[key])
        write_report(report, report_path)
        prune_report_files(report_path.parent)
        exit_code = 0 if not report["失败项"] else 1
        logger.info("平台任务结束 output=%r report=%r code=%d", str(output), str(report_path), exit_code)
        return exit_code, output, report_path
    finally:
        prune_run_logs(log_path.parent)
        close_run_file_logging()


def run_platform_workflow(args: Any) -> int:
    """执行平台兼容模式并支持单产品与批处理。

    参数：
        args：统一入口参数。
    返回值：
        全部产品中的最严重退出码。
    """
    source_arg = resolve_path(args.source)
    template = resolve_path(args.template) if args.template else default_template_path()
    output_arg = resolve_path(args.output) if args.output else default_output_path()
    assert source_arg is not None and output_arg is not None
    products = detect_batch(source_arg)
    if products and args.report:
        raise RuntimeError("批处理模式不能为多个产品共用一个 --report 文件")
    if products:
        worst = 0
        for product_dir in products:
            code, _, _ = run_single(product_dir, template, output_arg, args.platform)
            worst = max(worst, code)
        return worst
    report = resolve_path(args.report) if args.report else None
    code, _, _ = run_single(source_arg, template, output_arg, args.platform, report)
    return code
