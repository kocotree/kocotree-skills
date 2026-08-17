#!/usr/bin/env python3
"""校验台账中的字体专项检查是否完成数量闭环。"""

from __future__ import annotations

import argparse
import csv
import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any


LOGGER = logging.getLogger("typography_review_validation")
COUNT_FIELDS = {
    "found": "watch_character_found_count",
    "checked": "watch_character_checked_count",
    "abnormal": "watch_character_abnormal_count",
    "unreviewed": "watch_character_unreviewed_count",
}


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


def parse_count(row: dict[str, str], field: str, relative_path: str) -> int:
    """读取非负整数字段。

    参数：
        row: 当前 CSV 台账行。
        field: 需要读取的字段名。
        relative_path: 用于错误定位的文件相对路径。

    返回值：
        解析后的非负整数。
    """

    raw_value = row.get(field, "").strip()
    if raw_value == "":
        raise ValueError(f"{relative_path} 缺少字段值：{field}")
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{relative_path} 的 {field} 不是整数：{raw_value}") from exc
    if value < 0:
        raise ValueError(f"{relative_path} 的 {field} 不能为负数：{value}")
    return value


def validate_inventory(inventory: Path) -> dict[str, Any]:
    """校验字体专项字段并汇总每个配置的检查数量。

    参数：
        inventory: 已完成人工填写的 CSV 台账路径。

    返回值：
        包含校验结果、错误列表和各字体配置统计的字典。
    """

    resolved_inventory = inventory.resolve()
    LOGGER.info("开始校验字体专项台账：%s", resolved_inventory)
    errors: list[str] = []
    totals: dict[str, dict[str, int]] = defaultdict(
        lambda: {"images": 0, "found": 0, "checked": 0, "abnormal": 0, "unreviewed": 0}
    )

    with resolved_inventory.open("r", newline="", encoding="utf-8-sig") as source:
        reader = csv.DictReader(source)
        missing_columns = sorted(
            {
                "relative_path",
                "typography_profile_id",
                "typography_reference_status",
                "typography_occurrence_locations",
                *COUNT_FIELDS.values(),
            }
            - set(reader.fieldnames or [])
        )
        if missing_columns:
            raise ValueError(f"台账缺少字体专项字段：{missing_columns}")

        for row in reader:
            profile_id = row["typography_profile_id"].strip()
            if not profile_id:
                continue
            relative_path = row["relative_path"].strip() or "<unknown>"
            try:
                counts = {
                    name: parse_count(row, field, relative_path)
                    for name, field in COUNT_FIELDS.items()
                }
                if counts["found"] != counts["checked"] + counts["unreviewed"]:
                    errors.append(
                        f"{relative_path} 数量关系不成立：发现={counts['found']}，"
                        f"已检查={counts['checked']}，未检查={counts['unreviewed']}"
                    )
                if counts["abnormal"] > counts["checked"]:
                    errors.append(
                        f"{relative_path} 异常数量大于已检查数量："
                        f"异常={counts['abnormal']}，已检查={counts['checked']}"
                    )
                if counts["unreviewed"] != 0:
                    errors.append(f"{relative_path} 仍有 {counts['unreviewed']} 个关注字符未检查")
                if row["typography_reference_status"].strip() != "checked":
                    errors.append(f"{relative_path} 的标准字形参考状态必须为 checked")
                if counts["abnormal"] > 0 and not row[
                    "typography_occurrence_locations"
                ].strip():
                    errors.append(f"{relative_path} 存在字体异常但未填写出现位置")
                profile_totals = totals[profile_id]
                profile_totals["images"] += 1
                for name, value in counts.items():
                    profile_totals[name] += value
                LOGGER.info(
                    "完成字体专项行校验：%s；发现=%s；已检查=%s；异常=%s；未检查=%s",
                    relative_path,
                    counts["found"],
                    counts["checked"],
                    counts["abnormal"],
                    counts["unreviewed"],
                )
            except ValueError as exc:
                errors.append(str(exc))

    result = {
        "schema_version": 1,
        "inventory": str(resolved_inventory),
        "valid": not errors,
        "errors": errors,
        "profiles": dict(totals),
    }
    if errors:
        for error in errors:
            LOGGER.error("字体专项校验失败：%s", error)
    else:
        LOGGER.info("字体专项台账校验通过：配置=%s 个", len(totals))
    return result


def parse_args() -> argparse.Namespace:
    """解析命令行参数。

    参数：
        无。

    返回值：
        包含台账路径、汇总输出路径和日志级别的参数对象。
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inventory", type=Path, help="已完成人工填写的 CSV 台账")
    parser.add_argument("--summary-output", type=Path, help="校验汇总 JSON 输出路径")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="日志级别",
    )
    return parser.parse_args()


def main() -> int:
    """执行字体专项台账校验主流程。

    参数：
        无，参数从命令行读取。

    返回值：
        校验通过返回 0；字段缺失、数量未闭环或文件读取失败时返回 1。
    """

    args = parse_args()
    configure_logging(args.log_level)
    try:
        result = validate_inventory(args.inventory)
        if args.summary_output is not None:
            args.summary_output.parent.mkdir(parents=True, exist_ok=True)
            args.summary_output.write_text(
                json.dumps(result, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            LOGGER.info("已写入字体专项校验汇总：%s", args.summary_output.resolve())
    except Exception:
        LOGGER.exception("字体专项台账校验执行失败")
        return 1
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
