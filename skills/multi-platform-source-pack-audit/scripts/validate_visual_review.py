#!/usr/bin/env python3
"""校验原始数据包视觉复核台账是否达到报告交付条件。"""

from __future__ import annotations

import argparse
import csv
import json
import logging
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger("visual_review_validator")
DEFAULT_CONFIG = (
    Path(__file__).resolve().parent.parent
    / "assets"
    / "configs"
    / "visual-review-rules.json"
)
EDGE_FIELDS = (
    "edge_top_status",
    "edge_right_status",
    "edge_bottom_status",
    "edge_left_status",
)
TEXT_CHECK_FIELDS = (
    "typo_status",
    "missing_extra_character_status",
    "grammar_status",
    "verb_collocation_status",
)
REQUIRED_FIELDS = {
    "relative_path",
    "module",
    "is_image",
    "review_status",
    "edge_alignment_status",
    "internal_seam_status",
    "edge_review_notes",
    "edge_evidence_path",
    "text_presence_status",
    "visible_text_transcript",
    "text_content_status",
    "text_review_notes",
    "text_evidence_path",
    "issue_status",
    "issue_summary",
    "evidence_path",
    *EDGE_FIELDS,
    *TEXT_CHECK_FIELDS,
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


def load_config(config_path: Path) -> dict[str, Any]:
    """读取并验证视觉复核配置。

    参数：
        config_path: 视觉复核 JSON 配置路径。

    返回值：
        包含适用模块、状态集合和证据规则的配置字典。
    """

    config = json.loads(config_path.resolve().read_text(encoding="utf-8"))
    required = {
        "outer_edge_modules",
        "internal_seam_modules",
        "completed_review_status",
        "completed_check_statuses",
        "not_applicable_status",
        "text_presence_statuses",
        "issue_statuses",
        "statuses_requiring_notes",
        "confirmed_issue_statuses",
    }
    missing = sorted(required - set(config))
    if missing:
        raise ValueError(f"视觉复核配置缺少字段：{missing}")
    for field in (
        "outer_edge_modules",
        "internal_seam_modules",
        "completed_check_statuses",
        "text_presence_statuses",
        "issue_statuses",
        "statuses_requiring_notes",
        "confirmed_issue_statuses",
    ):
        if not isinstance(config[field], list) or not config[field]:
            raise ValueError(f"视觉复核配置 {field} 必须是非空列表")
    return config


def matches_scope(
    module: str,
    relative_path: str,
    configured_modules: list[str],
) -> bool:
    """判断台账模块或相对路径是否位于配置范围内。"""

    scopes = {str(item).casefold() for item in configured_modules}
    path_parts = {part.casefold() for part in Path(relative_path).parts[:-1]}
    if module:
        path_parts.add(module.casefold())
    return "*" in scopes or bool(path_parts & scopes)


def add_error(
    errors: list[dict[str, Any]],
    row_number: int,
    relative_path: str,
    field: str,
    message: str,
) -> None:
    """向错误清单追加一条结构化校验结果。"""

    errors.append(
        {
            "row": row_number,
            "relative_path": relative_path,
            "field": field,
            "message": message,
        }
    )


def require_completed_status(
    row: dict[str, str],
    field: str,
    completed_statuses: set[str],
    errors: list[dict[str, Any]],
    row_number: int,
    relative_path: str,
) -> bool:
    """检查指定字段是否包含可计入完成数量的状态。"""

    status = row.get(field, "").strip()
    if status in completed_statuses:
        return True
    add_error(
        errors,
        row_number,
        relative_path,
        field,
        f"需要填写完成状态，可用值：{sorted(completed_statuses)}",
    )
    return False


def validate_issue_evidence(
    row: dict[str, str],
    fields: tuple[str, ...],
    notes_field: str,
    evidence_field: str,
    config: dict[str, Any],
    errors: list[dict[str, Any]],
    row_number: int,
    relative_path: str,
) -> None:
    """校验问题状态对应的说明和证据是否完整。"""

    issue_statuses = {str(item) for item in config["issue_statuses"]}
    notes_statuses = {str(item) for item in config["statuses_requiring_notes"]}
    statuses = {row.get(field, "").strip() for field in fields}
    if statuses & notes_statuses and not row.get(notes_field, "").strip():
        add_error(
            errors,
            row_number,
            relative_path,
            notes_field,
            "问题或待复核状态必须填写复核说明",
        )
    if statuses & issue_statuses and not row.get(evidence_field, "").strip():
        add_error(
            errors,
            row_number,
            relative_path,
            evidence_field,
            "已确认问题必须填写证据路径",
        )


def validate_visual_review(
    inventory_path: Path,
    config: dict[str, Any],
) -> dict[str, Any]:
    """验证视觉复核台账字段、覆盖数量和问题证据。

    参数：
        inventory_path: 已填写审核结果的 CSV 台账路径。
        config: 已验证的视觉复核配置。

    返回值：
        包含是否通过、完成统计和逐项错误的汇总字典。
    """

    resolved_inventory = inventory_path.resolve()
    with resolved_inventory.open(newline="", encoding="utf-8-sig") as source:
        reader = csv.DictReader(source)
        fieldnames = set(reader.fieldnames or [])
        missing_fields = sorted(REQUIRED_FIELDS - fieldnames)
        if missing_fields:
            raise ValueError(f"视觉复核台账缺少字段：{missing_fields}")
        rows = list(reader)

    completed_review_status = str(config["completed_review_status"])
    completed_statuses = {str(item) for item in config["completed_check_statuses"]}
    not_applicable = str(config["not_applicable_status"])
    text_presence_statuses = {str(item) for item in config["text_presence_statuses"]}
    confirmed_issue_statuses = {
        str(item) for item in config["confirmed_issue_statuses"]
    }
    outer_modules = [str(item) for item in config["outer_edge_modules"]]
    seam_modules = [str(item) for item in config["internal_seam_modules"]]
    errors: list[dict[str, Any]] = []
    stats = {
        "images_total": 0,
        "images_checked": 0,
        "outer_edge_images": 0,
        "outer_edge_checks_expected": 0,
        "outer_edge_checks_completed": 0,
        "internal_seam_checks_expected": 0,
        "internal_seam_checks_completed": 0,
        "text_presence_checks_expected": 0,
        "text_presence_checks_completed": 0,
        "text_images": 0,
        "text_checks_expected": 0,
        "text_checks_completed": 0,
        "confirmed_issue_rows": 0,
        "confirmed_issue_rows_with_evidence": 0,
    }

    for row_number, row in enumerate(rows, start=2):
        if row.get("is_image", "").strip().casefold() != "true":
            continue
        relative_path = row.get("relative_path", "").strip()
        module = row.get("module", "").strip()
        stats["images_total"] += 1
        if row.get("review_status", "").strip() == completed_review_status:
            stats["images_checked"] += 1
        else:
            add_error(
                errors,
                row_number,
                relative_path,
                "review_status",
                f"图片复核完成状态必须为 {completed_review_status}",
            )

        if matches_scope(module, relative_path, outer_modules):
            stats["outer_edge_images"] += 1
            stats["outer_edge_checks_expected"] += len(EDGE_FIELDS)
            for field in EDGE_FIELDS:
                if require_completed_status(
                    row,
                    field,
                    completed_statuses,
                    errors,
                    row_number,
                    relative_path,
                ):
                    stats["outer_edge_checks_completed"] += 1
            require_completed_status(
                row,
                "edge_alignment_status",
                completed_statuses,
                errors,
                row_number,
                relative_path,
            )
            validate_issue_evidence(
                row,
                EDGE_FIELDS,
                "edge_review_notes",
                "edge_evidence_path",
                config,
                errors,
                row_number,
                relative_path,
            )

        if matches_scope(module, relative_path, seam_modules):
            stats["internal_seam_checks_expected"] += 1
            if require_completed_status(
                row,
                "internal_seam_status",
                completed_statuses,
                errors,
                row_number,
                relative_path,
            ):
                stats["internal_seam_checks_completed"] += 1
            validate_issue_evidence(
                row,
                ("internal_seam_status",),
                "edge_review_notes",
                "edge_evidence_path",
                config,
                errors,
                row_number,
                relative_path,
            )
        elif row.get("internal_seam_status", "").strip() != not_applicable:
            add_error(
                errors,
                row_number,
                relative_path,
                "internal_seam_status",
                f"非适用模块应填写 {not_applicable}",
            )

        stats["text_presence_checks_expected"] += 1
        text_presence = row.get("text_presence_status", "").strip()
        if text_presence in text_presence_statuses:
            stats["text_presence_checks_completed"] += 1
        else:
            add_error(
                errors,
                row_number,
                relative_path,
                "text_presence_status",
                f"需要判断图片文字状态，可用值：{sorted(text_presence_statuses)}",
            )
            text_presence = ""

        if text_presence == "present":
            stats["text_images"] += 1
            stats["text_checks_expected"] += len(TEXT_CHECK_FIELDS)
            if not row.get("visible_text_transcript", "").strip():
                add_error(
                    errors,
                    row_number,
                    relative_path,
                    "visible_text_transcript",
                    "含文字图片必须填写可见文字转录",
                )
            for field in TEXT_CHECK_FIELDS:
                if require_completed_status(
                    row,
                    field,
                    completed_statuses,
                    errors,
                    row_number,
                    relative_path,
                ):
                    stats["text_checks_completed"] += 1
            require_completed_status(
                row,
                "text_content_status",
                completed_statuses,
                errors,
                row_number,
                relative_path,
            )
            validate_issue_evidence(
                row,
                TEXT_CHECK_FIELDS,
                "text_review_notes",
                "text_evidence_path",
                config,
                errors,
                row_number,
                relative_path,
            )
        elif text_presence in {"absent", "unreadable"}:
            for field in (*TEXT_CHECK_FIELDS, "text_content_status"):
                if row.get(field, "").strip() != not_applicable:
                    add_error(
                        errors,
                        row_number,
                        relative_path,
                        field,
                        f"当前文字状态下应填写 {not_applicable}",
                    )
            if (
                text_presence == "unreadable"
                and not row.get("text_review_notes", "").strip()
            ):
                add_error(
                    errors,
                    row_number,
                    relative_path,
                    "text_review_notes",
                    "文字不可辨认时必须说明原因和处理方式",
                )

        if row.get("issue_status", "").strip() in confirmed_issue_statuses:
            stats["confirmed_issue_rows"] += 1
            has_summary = bool(row.get("issue_summary", "").strip())
            has_evidence = bool(row.get("evidence_path", "").strip())
            if has_summary and has_evidence:
                stats["confirmed_issue_rows_with_evidence"] += 1
            if not has_summary:
                add_error(
                    errors,
                    row_number,
                    relative_path,
                    "issue_summary",
                    "已确认问题必须填写问题摘要",
                )
            if not has_evidence:
                add_error(
                    errors,
                    row_number,
                    relative_path,
                    "evidence_path",
                    "已确认问题必须填写完整证据路径",
                )

    return {
        "schema_version": 1,
        "inventory": str(resolved_inventory),
        "valid": not errors,
        "error_count": len(errors),
        "stats": stats,
        "errors": errors,
    }


def parse_args() -> argparse.Namespace:
    """解析命令行参数。

    参数：
        无。

    返回值：
        包含台账、配置、汇总输出和日志选项的参数对象。
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inventory", type=Path, help="已填写审核结果的 CSV 台账")
    parser.add_argument(
        "--config", type=Path, default=DEFAULT_CONFIG, help="视觉复核配置"
    )
    parser.add_argument("--summary-output", type=Path, help="JSON 校验汇总输出路径")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="日志级别",
    )
    return parser.parse_args()


def main() -> int:
    """执行视觉复核完成校验主流程。

    参数：
        无，参数从命令行读取。

    返回值：
        台账达到交付条件时返回 0；存在遗漏或输入异常时返回 1。
    """

    args = parse_args()
    configure_logging(args.log_level)
    try:
        LOGGER.info("开始校验视觉复核台账：%s", args.inventory.resolve())
        config = load_config(args.config)
        summary = validate_visual_review(args.inventory, config)
        if args.summary_output is not None:
            args.summary_output.parent.mkdir(parents=True, exist_ok=True)
            args.summary_output.write_text(
                json.dumps(summary, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            LOGGER.info("已写入视觉复核校验汇总：%s", args.summary_output.resolve())
        if not summary["valid"]:
            LOGGER.error("视觉复核校验未通过：%s 项", summary["error_count"])
            return 1
        LOGGER.info("视觉复核校验通过：%s", summary["stats"])
    except Exception:
        LOGGER.exception("视觉复核校验失败")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
