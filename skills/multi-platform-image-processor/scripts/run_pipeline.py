from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from build_tmall_master import build as build_tmall
from common import (
    全部平台,
    平台目录名,
    copy_template_empty_dirs,
    new_report,
    add_platform_result,
    add_failure,
    resolve_path,
    ensure_dir,
)
from derive_cbme import derive as derive_cbme
from derive_fengxiang_aikucun import derive as derive_fengxiang_aikucun
from derive_jd import derive as derive_jd
from derive_offsite import derive as derive_offsite
from derive_vip import derive as derive_vip
from quality_audit import run_quality_audit
from scan_source_pack import scan_source_pack
from write_report import write_report
from auth.auth_client import ensure_token

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
    if source.name == "数据包":
        product_name = source.parent.name
        return source, output_root / product_name, product_name

    data_pack = source / "数据包"
    if data_pack.is_dir():
        return data_pack, output_root / source.name, source.name

    return source, output_root, ""


def main(argv: list[str] | None = None) -> int:
    ensure_token()
    args = parse_args(argv or sys.argv[1:])
    source_arg = resolve_path(args.source)
    template = resolve_path(args.template) if args.template else default_template_path()
    output_arg = resolve_path(args.output) if args.output else default_output_path()
    source = source_arg
    output = output_arg
    product_name = ""
    if source_arg is not None and output_arg is not None:
        source, output, product_name = resolve_source_and_output(source_arg, output_arg)
    report_path = resolve_path(args.report) if args.report else default_report_path(output)

    assert source is not None
    assert output is not None
    assert report_path is not None
    ensure_dir(output)
    report = new_report(source, template, output, args.platform)
    if product_name:
        report["处理配置"]["产品名"] = product_name
        report["处理配置"]["源参数目录"] = str(source_arg)
        report["处理配置"]["输出根目录"] = str(output_arg)

    if not source.exists():
        add_failure(report, "源数据包目录不存在", 源目录=str(source))
        write_report(report, report_path)
        prune_report_files(report_path.parent)
        return 2

    selected = 全部平台 if args.platform == "all" else [args.platform]
    if "tmall" not in selected:
        tmall_needed = any(p in selected for p in ["cbme", "jd", "vip", "fengxiang-aikucun"])
    else:
        tmall_needed = True

    report["素材扫描"] = scan_source_pack(source)

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


if __name__ == "__main__":
    raise SystemExit(main())
