from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

from auth.auth_client import ensure_token
from common import (
    全部平台,
    平台目录名,
    copy_template_empty_dirs,
    new_report,
    add_platform_result,
    add_failure,
    add_warning,
    resolve_path,
    ensure_dir,
)
from common.quality_audit import run_quality_audit
from common.scan_source_pack import scan_source_pack
from common.source_pack_validator import validate_source_pack
from common.write_report import write_report
from platforms.tmall import build as build_tmall
from platforms.cbme import derive as derive_cbme
from platforms.fengxiang_aikucun import derive as derive_fengxiang_aikucun
from platforms.jd import derive as derive_jd
from platforms.offsite import derive as derive_offsite
from platforms.vip import derive as derive_vip

def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="全自动处理多平台商品图片包并输出中文报告。")
    parser.add_argument("--source", required=True, help="源数据包目录")
    parser.add_argument("--template", default="", help="模板目录，默认使用 skill 内置 template")
    parser.add_argument("--output", default="", help="输出目录，默认桌面 multi-platform-image-processor/output")
    parser.add_argument(
        "--platform",
        default="all",
        choices=["all", *全部平台],
        help="要输出的平台，默认 all",
    )
    parser.add_argument("--report", default="", help="报告 JSON 路径，默认保存到 scripts/output/report")
    return parser.parse_args(argv)


def default_report_path(output: Path) -> Path:
    safe_name = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in output.name).strip("_")
    if not safe_name:
        safe_name = "output"
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path(__file__).resolve().parent / "output" / "report" / f"{safe_name}-{timestamp}-report.json"


def prune_report_files(report_dir: Path, keep: int = 100) -> None:
    reports = sorted(
        report_dir.glob("*-report.json"),
        key=lambda path: (path.stat().st_mtime, path.name),
        reverse=True,
    )
    for old_report in reports[keep:]:
        old_report.unlink(missing_ok=True)


def default_template_path() -> Path:
    return Path(__file__).resolve().parents[1] / "template"


def default_output_path() -> Path:
    desktop = Path("E:/桌面")
    if not desktop.exists():
        desktop = Path.home() / "Desktop"
    return desktop / "multi-platform-image-processor" / "output"


def resolve_source_and_output(source: Path, output_root: Path) -> tuple[Path, Path, str]:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    if source.name == "数据包":
        product_name = source.parent.name
        return source, output_root / f"{product_name}_{timestamp}", product_name

    data_pack = source / "数据包"
    if data_pack.is_dir():
        return data_pack, output_root / f"{source.name}_{timestamp}", source.name

    return source, output_root / timestamp, ""


def detect_batch(source: Path) -> list[Path]:
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
    report_path: Path | None = None,
) -> int:
    source, output, product_name = resolve_source_and_output(source_arg, output_arg)
    if report_path is None:
        report_path = default_report_path(output)

    report = new_report(source, template, output, platform)
    if product_name:
        report["处理配置"]["产品名"] = product_name
        report["处理配置"]["源参数目录"] = str(source_arg)
        report["处理配置"]["输出根目录"] = str(output_arg)

    if not source.exists():
        add_failure(report, "源数据包目录不存在", 源目录=str(source))
        write_report(report, report_path)
        prune_report_files(report_path.parent)
        return 2

    validation = validate_source_pack(source)
    report["输入包检测"] = validation
    report["素材扫描"] = scan_source_pack(source)
    for warning in validation["警告"]:
        add_warning(
            report,
            warning["信息"],
            **{key: value for key, value in warning.items() if key != "信息"},
        )
    if not validation["通过"]:
        for problem in validation["问题"]:
            add_failure(
                report,
                "输入包检测失败",
                问题=problem["信息"],
                **{key: value for key, value in problem.items() if key != "信息"},
            )
        logging.getLogger(__name__).error(
            "输入包检测失败，停止处理：%s，共%d项问题",
            source,
            len(validation["问题"]),
        )
        write_report(report, report_path)
        prune_report_files(report_path.parent)
        print(f"输入包检测失败，已停止处理：{source}")
        print("标准输入结构：")
        print(validation["标准输入结构"])
        print(f"报告路径：{report_path}")
        return 2

    ensure_dir(output)

    selected = 全部平台 if platform == "all" else [platform]
    if "tmall" not in selected:
        tmall_needed = any(p in selected for p in ["cbme", "jd", "vip", "fengxiang-aikucun"])
    else:
        tmall_needed = True

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
    print(f"处理完成：{output}")
    print(f"报告路径：{report_path}")
    return 0 if not report["失败项"] else 1


def main(argv: list[str] | None = None) -> int:
    """执行多平台图片包处理主流程。

    参数：
        argv：可选命令行参数列表；未提供时读取系统命令行参数。
    返回值：
        0 表示成功，1 表示存在失败项或认证失败，2 表示源目录不存在。
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    try:
        ensure_token()
    except SystemExit:
        return 1
    except RuntimeError as e:
        print(f"认证失败：{e}")
        return 1

    args = parse_args(argv or sys.argv[1:])
    source_arg = resolve_path(args.source)
    template = resolve_path(args.template) if args.template else default_template_path()
    output_arg = resolve_path(args.output) if args.output else default_output_path()

    assert source_arg is not None
    assert output_arg is not None

    products = detect_batch(source_arg)
    if products:
        print(f"检测到批处理模式，共 {len(products)} 个产品：")
        for p in products:
            print(f"  - {p.name}")
        worst = 0
        for product_dir in products:
            print(f"\n{'='*60}")
            print(f"开始处理：{product_dir.name}")
            print(f"{'='*60}")
            report_path = resolve_path(args.report) if args.report else None
            code = run_single(product_dir, template, output_arg, args.platform, report_path)
            worst = max(worst, code)
        print(f"\n全部处理完成，共 {len(products)} 个产品。")
        return worst

    report_path = resolve_path(args.report) if args.report else None
    return run_single(source_arg, template, output_arg, args.platform, report_path)


if __name__ == "__main__":
    raise SystemExit(main())
