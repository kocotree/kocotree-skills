from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .run_logging import report_artifact_prefix
from .utils import (
    build_image_statistics,
    build_png_compression_statistics,
    ensure_dir,
    finalize_report_summary,
    write_json,
)


logger = logging.getLogger(__name__)


def image_records_path(report_path: Path) -> Path:
    """返回主报告对应的逐图明细文件路径。"""
    if report_path.name == "report.json":
        return report_path.with_name("image-records.jsonl")
    return report_path.with_name(f"{report_artifact_prefix(report_path)}-image-records.jsonl")


def write_image_records(
    records: list[dict[str, Any]],
    path: Path,
    run_id: str,
    product: str,
) -> None:
    """以 JSONL 格式写出逐图处理明细。

    参数：
        records：本次运行产生的逐图处理记录。
        path：逐图明细文件保存路径。
        run_id：本次运行的唯一标识。
        product：当前处理的产品名称。
    返回值：
        无返回值。
    """
    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for record in records:
            item = {"运行ID": run_id, "产品": product, **record}
            stream.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")))
            stream.write("\n")


def write_report(report: dict, path: Path) -> None:
    """写出精简主报告和独立逐图明细。

    功能说明：主报告保留处理统计、异常和追溯路径；每张图片的完整处理
    记录写入同前缀 JSONL 文件。

    参数：
        report：处理过程中累计的报告数据。
        path：精简主报告 JSON 保存路径。
    返回值：
        无返回值。
    """
    records = list(report.get("图片记录", []))
    main_report = {key: value for key, value in report.items() if key != "图片记录"}
    detail_path = image_records_path(path)
    config = main_report.get("处理配置", {})
    run_id = str(config.get("运行ID", report_artifact_prefix(path)))
    product = str(config.get("产品名", ""))

    write_image_records(records, detail_path, run_id, product)
    main_report["图片统计"] = build_image_statistics(records)
    main_report["PNG压缩统计"] = build_png_compression_statistics(records)
    trace_files = dict(main_report.get("追溯文件", {}))
    trace_files["逐图明细"] = str(detail_path.resolve())
    main_report["追溯文件"] = trace_files
    finalize_report_summary(main_report, len(records))
    write_json(path, main_report)
    logger.info(
        "报告写入完成 report=%r image_records=%r image_count=%d",
        str(path),
        str(detail_path),
        len(records),
        extra={
            "stage": "报告",
            "event": "报告写入",
            "status": "success",
        },
    )
