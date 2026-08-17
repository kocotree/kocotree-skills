#!/usr/bin/env python3
"""将旧版 Excel `.xls` 工作簿只读提取为 JSON。"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
from pathlib import Path
from typing import Any

import xlrd
from xlrd.biffh import error_text_from_code
from xlrd.xldate import XLDateError, xldate_as_datetime

LOGGER = logging.getLogger("xls_extractor")


def configure_logging(level: str) -> None:
    """配置标准日志输出。

    参数：
        level: 日志级别名称，例如 INFO 或 WARNING。

    返回值：
        无。
    """

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
    )


def calculate_sha256(path: Path) -> str:
    """计算工作簿文件的 SHA-256。"""

    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def convert_cell(cell: xlrd.sheet.Cell, datemode: int) -> Any:
    """将 xlrd 单元格转换为 JSON 可序列化的值。

    参数：
        cell: 需要转换的 xlrd 单元格。
        datemode: 工作簿日期系统编号。

    返回值：
        文本、数字、布尔值、日期字符串、错误对象或空值。
    """

    if cell.ctype in {xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK}:
        return None
    if cell.ctype == xlrd.XL_CELL_TEXT:
        return str(cell.value)
    if cell.ctype == xlrd.XL_CELL_NUMBER:
        number = float(cell.value)
        return int(number) if number.is_integer() else number
    if cell.ctype == xlrd.XL_CELL_DATE:
        try:
            return xldate_as_datetime(cell.value, datemode).isoformat(sep=" ")
        except XLDateError:
            LOGGER.warning("日期序列值无法转换：%s", cell.value)
            return {"date_serial": cell.value, "conversion_status": "failed"}
    if cell.ctype == xlrd.XL_CELL_BOOLEAN:
        return bool(cell.value)
    if cell.ctype == xlrd.XL_CELL_ERROR:
        error_code = int(cell.value)
        return {
            "error_code": error_code,
            "error_text": error_text_from_code.get(error_code, "unknown"),
        }
    return cell.value


def extract_workbook(source: Path) -> dict[str, Any]:
    """读取 `.xls` 工作簿并提取所有工作表。

    参数：
        source: 需要读取的 `.xls` 文件路径。

    返回值：
        包含文件属性、工作表结构和单元格数据的字典。
    """

    resolved_source = source.resolve()
    if resolved_source.suffix.casefold() != ".xls":
        raise ValueError(f"仅支持旧版 .xls 工作簿：{resolved_source}")
    if not resolved_source.is_file():
        raise FileNotFoundError(f"工作簿不存在：{resolved_source}")

    LOGGER.info("开始只读提取工作簿：%s", resolved_source)
    workbook = xlrd.open_workbook(
        filename=str(resolved_source),
        formatting_info=True,
        on_demand=True,
    )
    datemode = workbook.datemode
    sheets: list[dict[str, Any]] = []
    try:
        for sheet_index in range(workbook.nsheets):
            sheet = workbook.sheet_by_index(sheet_index)
            rows: list[list[Any]] = []
            for row_index in range(sheet.nrows):
                values = [
                    convert_cell(sheet.cell(row_index, column_index), datemode)
                    for column_index in range(sheet.ncols)
                ]
                while values and values[-1] is None:
                    values.pop()
                rows.append(values)
            sheets.append(
                {
                    "index": sheet_index,
                    "name": sheet.name,
                    "visibility": sheet.visibility,
                    "row_count": sheet.nrows,
                    "column_count": sheet.ncols,
                    "merged_cells": [list(area) for area in sheet.merged_cells],
                    "rows": rows,
                }
            )
            LOGGER.info(
                "已提取工作表 %s/%s：%s；行=%s；列=%s",
                sheet_index + 1,
                workbook.nsheets,
                sheet.name,
                sheet.nrows,
                sheet.ncols,
            )
    finally:
        workbook.release_resources()

    result = {
        "schema_version": 1,
        "source": str(resolved_source),
        "bytes": resolved_source.stat().st_size,
        "sha256": calculate_sha256(resolved_source),
        "datemode": datemode,
        "sheet_count": len(sheets),
        "sheets": sheets,
    }
    LOGGER.info("工作簿提取完成：工作表=%s", len(sheets))
    return result


def parse_args() -> argparse.Namespace:
    """解析命令行参数。

    参数：
        无。

    返回值：
        包含输入路径、输出路径和日志级别的参数对象。
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="需要读取的旧版 .xls 工作簿")
    parser.add_argument("--output", type=Path, required=True, help="JSON 输出路径")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="日志级别",
    )
    return parser.parse_args()


def main() -> int:
    """执行 `.xls` 工作簿只读提取主流程。

    参数：
        无，参数从命令行读取。

    返回值：
        成功返回 0；输入或输出处理失败时返回 1。
    """

    args = parse_args()
    configure_logging(args.log_level)
    try:
        result = extract_workbook(args.source)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        LOGGER.info("已写入工作簿 JSON：%s", args.output.resolve())
    except Exception:
        LOGGER.exception("工作簿提取失败")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
