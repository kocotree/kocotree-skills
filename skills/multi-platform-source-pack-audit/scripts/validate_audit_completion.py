#!/usr/bin/env python3
"""校验视觉复核、平台驳回词和材质成分审核是否完整闭环。"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from cleanup_work import DEFAULT_WORK_DIR, cleanup_work_directory
from validate_visual_review import (
    DEFAULT_CONFIG as DEFAULT_VISUAL_CONFIG,
)
from validate_visual_review import (
    load_config as load_visual_config,
)
from validate_visual_review import validate_visual_review

LOGGER = logging.getLogger("audit_completion_validator")
DEFAULT_PROHIBITED_CONFIG = (
    Path(__file__).resolve().parent.parent
    / "assets"
    / "configs"
    / "platform-prohibited-terms.json"
)
DEFAULT_COMPLETION_CONFIG = (
    Path(__file__).resolve().parent.parent
    / "assets"
    / "configs"
    / "audit-completion-rules.json"
)
MATERIAL_FIELDS = {
    "material_claim_presence_status",
    "material_claim_transcript",
    "material_reference_status",
    "material_reference_path",
    "material_reference_composition",
    "material_composition_status",
    "material_difference",
    "material_review_notes",
    "material_evidence_path",
}
REQUIRED_INVENTORY_FIELDS = {
    "relative_path",
    "is_image",
    "text_presence_status",
    "ad_compliance_status",
    *MATERIAL_FIELDS,
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


def calculate_text_input_sha256(rows: list[dict[str, str]]) -> str:
    """计算驳回词扫描输入字段的稳定 SHA-256 哈希。"""

    payload = [
        {
            "relative_path": row.get("relative_path", ""),
            "is_image": row.get("is_image", ""),
            "text_presence_status": row.get("text_presence_status", ""),
            "visible_text_transcript": row.get("visible_text_transcript", ""),
        }
        for row in rows
    ]
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def calculate_file_sha256(path: Path) -> str:
    """计算配置文件的 SHA-256 哈希。"""

    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_completion_config(config_path: Path) -> dict[str, Any]:
    """读取并验证完整审核校验配置。

    参数：
        config_path: 完整审核校验 JSON 配置路径。

    返回值：
        包含状态集合和证据要求的配置字典。
    """

    config = json.loads(config_path.resolve().read_text(encoding="utf-8"))
    required = {
        "completed_statuses",
        "not_applicable_status",
        "material_presence_statuses",
        "material_reference_statuses",
        "term_review_statuses",
        "statuses_requiring_notes",
        "statuses_requiring_evidence",
    }
    missing = sorted(required - set(config))
    if missing:
        raise ValueError(f"完整审核校验配置缺少字段：{missing}")
    for field in required - {"not_applicable_status"}:
        if not isinstance(config[field], list) or not config[field]:
            raise ValueError(f"完整审核校验配置 {field} 必须是非空列表")
    return config


def load_inventory(inventory_path: Path) -> list[dict[str, str]]:
    """读取并验证完整审核台账。

    参数：
        inventory_path: 已填写审核结果的 CSV 台账路径。

    返回值：
        CSV 中的全部记录。
    """

    with inventory_path.resolve().open(newline="", encoding="utf-8-sig") as source:
        reader = csv.DictReader(source)
        fieldnames = set(reader.fieldnames or [])
        missing = sorted(REQUIRED_INVENTORY_FIELDS - fieldnames)
        if missing:
            raise ValueError(f"完整审核台账缺少字段：{missing}")
        return list(reader)


def add_error(
    errors: list[dict[str, Any]],
    source: str,
    relative_path: str,
    field: str,
    message: str,
    row: int | None = None,
) -> None:
    """向完整审核错误清单追加结构化结果。"""

    item: dict[str, Any] = {
        "source": source,
        "relative_path": relative_path,
        "field": field,
        "message": message,
    }
    if row is not None:
        item["row"] = row
    errors.append(item)


def validate_material_reviews(
    rows: list[dict[str, str]],
    config: dict[str, Any],
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    """校验逐图材质声明、权威依据和差异证据。

    参数：
        rows: 完整审核台账中的全部记录。
        config: 已验证的完整审核校验配置。

    返回值：
        材质审核统计，以及逐项错误列表。
    """

    presence_statuses = {str(item) for item in config["material_presence_statuses"]}
    reference_statuses = {str(item) for item in config["material_reference_statuses"]}
    completed_statuses = {str(item) for item in config["completed_statuses"]}
    notes_statuses = {str(item) for item in config["statuses_requiring_notes"]}
    evidence_statuses = {str(item) for item in config["statuses_requiring_evidence"]}
    not_applicable = str(config["not_applicable_status"])
    errors: list[dict[str, Any]] = []
    stats = {
        "images_expected": 0,
        "presence_completed": 0,
        "claim_images": 0,
        "claim_reviews_completed": 0,
        "issues": 0,
        "needs_evidence": 0,
    }
    for row_number, row in enumerate(rows, start=2):
        if row.get("is_image", "").strip().casefold() != "true":
            continue
        stats["images_expected"] += 1
        relative_path = row.get("relative_path", "").strip()
        presence = row.get("material_claim_presence_status", "").strip()
        if presence not in presence_statuses:
            add_error(
                errors,
                "material",
                relative_path,
                "material_claim_presence_status",
                f"需要判断材质文案状态，可用值：{sorted(presence_statuses)}",
                row_number,
            )
            continue
        stats["presence_completed"] += 1
        composition_status = row.get("material_composition_status", "").strip()
        reference_status = row.get("material_reference_status", "").strip()
        notes = row.get("material_review_notes", "").strip()
        evidence = row.get("material_evidence_path", "").strip()

        if presence == "absent":
            for field in ("material_reference_status", "material_composition_status"):
                if row.get(field, "").strip() != not_applicable:
                    add_error(
                        errors,
                        "material",
                        relative_path,
                        field,
                        f"无材质文案时应填写 {not_applicable}",
                        row_number,
                    )
            continue

        if presence == "unreadable":
            if composition_status not in {"needs_review", "needs_evidence"}:
                add_error(
                    errors,
                    "material",
                    relative_path,
                    "material_composition_status",
                    "材质文字不可辨认时必须标记 needs_review 或 needs_evidence",
                    row_number,
                )
            if not notes:
                add_error(
                    errors,
                    "material",
                    relative_path,
                    "material_review_notes",
                    "材质文字不可辨认时必须说明原因和复核方式",
                    row_number,
                )
            continue

        stats["claim_images"] += 1
        if not row.get("material_claim_transcript", "").strip():
            add_error(
                errors,
                "material",
                relative_path,
                "material_claim_transcript",
                "含材质文案图片必须填写原文转录",
                row_number,
            )
        if reference_status not in reference_statuses:
            add_error(
                errors,
                "material",
                relative_path,
                "material_reference_status",
                f"需要填写权威依据状态，可用值：{sorted(reference_statuses)}",
                row_number,
            )
        if composition_status not in completed_statuses:
            add_error(
                errors,
                "material",
                relative_path,
                "material_composition_status",
                f"需要填写材质核对状态，可用值：{sorted(completed_statuses)}",
                row_number,
            )
        else:
            stats["claim_reviews_completed"] += 1
            if composition_status == "issue":
                stats["issues"] += 1
            if composition_status == "needs_evidence":
                stats["needs_evidence"] += 1

        if reference_status == "matched":
            for field, message in (
                ("material_reference_path", "已匹配权威依据时必须填写具体文件路径"),
                (
                    "material_reference_composition",
                    "已匹配权威依据时必须填写标准成分原文",
                ),
            ):
                if not row.get(field, "").strip():
                    add_error(
                        errors,
                        "material",
                        relative_path,
                        field,
                        message,
                        row_number,
                    )
        elif reference_status in {"unavailable", "ambiguous"}:
            if composition_status != "needs_evidence":
                add_error(
                    errors,
                    "material",
                    relative_path,
                    "material_composition_status",
                    "权威依据不可用或不明确时必须标记 needs_evidence",
                    row_number,
                )
            if not notes:
                add_error(
                    errors,
                    "material",
                    relative_path,
                    "material_review_notes",
                    "权威依据不可用或不明确时必须说明缺少内容",
                    row_number,
                )

        if composition_status in notes_statuses and not notes:
            add_error(
                errors,
                "material",
                relative_path,
                "material_review_notes",
                "问题、待复核或待补证状态必须填写材质复核说明",
                row_number,
            )
        if composition_status in evidence_statuses and not evidence:
            add_error(
                errors,
                "material",
                relative_path,
                "material_evidence_path",
                "已确认材质问题必须填写证据路径",
                row_number,
            )
        if (
            composition_status == "issue"
            and not row.get("material_difference", "").strip()
        ):
            add_error(
                errors,
                "material",
                relative_path,
                "material_difference",
                "已确认材质问题必须列出图片值与标准值的差异",
                row_number,
            )
    return stats, errors


def validate_ad_compliance_statuses(
    rows: list[dict[str, str]],
    config: dict[str, Any],
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    """校验逐图广告合规状态是否与文字可读性对应。"""

    completed_statuses = {str(item) for item in config["completed_statuses"]}
    not_applicable = str(config["not_applicable_status"])
    errors: list[dict[str, Any]] = []
    stats = {"images_expected": 0, "completed": 0}
    for row_number, row in enumerate(rows, start=2):
        if row.get("is_image", "").strip().casefold() != "true":
            continue
        stats["images_expected"] += 1
        relative_path = row.get("relative_path", "").strip()
        text_presence = row.get("text_presence_status", "").strip()
        status = row.get("ad_compliance_status", "").strip()
        valid = False
        if text_presence == "present":
            valid = status in completed_statuses
        elif text_presence == "absent":
            valid = status == not_applicable
        elif text_presence == "unreadable":
            valid = status in {"needs_review", "needs_evidence"}
        if valid:
            stats["completed"] += 1
        else:
            add_error(
                errors,
                "ad_compliance",
                relative_path,
                "ad_compliance_status",
                "广告合规状态必须与图片文字存在性对应并完成填写",
                row_number,
            )
    return stats, errors


def validate_prohibited_term_audit(
    inventory_path: Path,
    rows: list[dict[str, str]],
    audit_path: Path,
    prohibited_config_path: Path,
    config: dict[str, Any],
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    """校验驳回词扫描覆盖、候选处理状态和台账联动。

    参数：
        inventory_path: 当前完整审核台账路径。
        rows: 完整审核台账中的全部记录。
        audit_path: 已人工复核的平台驳回词候选 JSON 路径。
        prohibited_config_path: 本次审核使用的平台驳回词配置路径。
        config: 已验证的完整审核校验配置。

    返回值：
        驳回词审核统计，以及逐项错误列表。
    """

    audit = json.loads(audit_path.resolve().read_text(encoding="utf-8"))
    errors: list[dict[str, Any]] = []
    review_statuses = {str(item) for item in config["term_review_statuses"]}
    notes_statuses = {str(item) for item in config["statuses_requiring_notes"]}
    evidence_statuses = {str(item) for item in config["statuses_requiring_evidence"]}
    image_rows = [
        row for row in rows if row.get("is_image", "").strip().casefold() == "true"
    ]
    text_images = [
        row
        for row in image_rows
        if row.get("text_presence_status", "").strip() == "present"
    ]
    expected_hash = calculate_text_input_sha256(rows)
    if audit.get("text_input_sha256") != expected_hash:
        add_error(
            errors,
            "prohibited_terms",
            "",
            "text_input_sha256",
            "驳回词结果与当前文字转录版本不一致，请重新扫描",
        )
    expected_config_hash = calculate_file_sha256(prohibited_config_path.resolve())
    if audit.get("config_sha256") != expected_config_hash:
        add_error(
            errors,
            "prohibited_terms",
            "",
            "config_sha256",
            "驳回词结果与当前规则配置不一致，请重新扫描",
        )
    if audit.get("scan_complete") is not True:
        add_error(
            errors,
            "prohibited_terms",
            "",
            "scan_complete",
            "驳回词扫描存在未完成的文字输入",
        )
    expected_counts = {
        "images_total": len(image_rows),
        "images_with_text": len(text_images),
        "transcripts_scanned": len(text_images),
    }
    for field, expected in expected_counts.items():
        if audit.get(field) != expected:
            add_error(
                errors,
                "prohibited_terms",
                "",
                field,
                f"驳回词扫描覆盖数量应为 {expected}，实际为 {audit.get(field)}",
            )

    row_by_path = {row.get("relative_path", "").strip(): row for row in image_rows}
    hits = audit.get("hits")
    if not isinstance(hits, list):
        raise TypeError("驳回词结果 hits 必须是列表")
    reviewed = 0
    issues = 0
    needs_evidence = 0
    false_positives = 0
    active_statuses_by_path: dict[str, set[str]] = {}
    for index, hit in enumerate(hits, start=1):
        if not isinstance(hit, dict):
            raise TypeError(f"驳回词结果第 {index} 项必须是对象")
        relative_path = str(hit.get("relative_path", "")).strip()
        status = str(hit.get("review_status", "")).strip()
        required = str(hit.get("required_disposition", "")).strip()
        notes = str(hit.get("review_notes", "")).strip()
        evidence = str(hit.get("evidence_path", "")).strip()
        if relative_path not in row_by_path:
            add_error(
                errors,
                "prohibited_terms",
                relative_path,
                "relative_path",
                "驳回词命中路径不在当前台账中",
            )
        if status not in review_statuses:
            add_error(
                errors,
                "prohibited_terms",
                relative_path,
                "review_status",
                f"命中项必须完成复核，可用值：{sorted(review_statuses)}",
            )
            continue
        reviewed += 1
        if status == "issue":
            issues += 1
        elif status == "needs_evidence":
            needs_evidence += 1
        else:
            false_positives += 1
        if status != "false_positive" and required and status != required:
            add_error(
                errors,
                "prohibited_terms",
                relative_path,
                "review_status",
                f"当前扫描范围要求状态为 {required}；如不适用请标记 false_positive 并说明",
            )
        if status in notes_statuses and not notes:
            add_error(
                errors,
                "prohibited_terms",
                relative_path,
                "review_notes",
                "驳回词复核结果必须填写完整语境和处理说明",
            )
        if status in evidence_statuses and not evidence:
            add_error(
                errors,
                "prohibited_terms",
                relative_path,
                "evidence_path",
                "已确认驳回词问题必须填写证据路径",
            )
        if status != "false_positive":
            active_statuses_by_path.setdefault(relative_path, set()).add(status)

    for relative_path, statuses in active_statuses_by_path.items():
        inventory_status = row_by_path.get(relative_path, {}).get(
            "ad_compliance_status", ""
        )
        expected = "issue" if "issue" in statuses else "needs_evidence"
        if inventory_status != expected:
            add_error(
                errors,
                "prohibited_terms",
                relative_path,
                "ad_compliance_status",
                f"台账广告合规状态应与命中结果一致：{expected}",
            )

    stats = {
        "hits": len(hits),
        "reviewed": reviewed,
        "issues": issues,
        "needs_evidence": needs_evidence,
        "false_positives": false_positives,
    }
    return stats, errors


def validate_audit_completion(
    inventory_path: Path,
    prohibited_term_audit_path: Path,
    prohibited_config_path: Path,
    visual_config: dict[str, Any],
    completion_config: dict[str, Any],
) -> dict[str, Any]:
    """执行完整审核交付前的统一校验。

    参数：
        inventory_path: 已填写审核结果的 CSV 台账路径。
        prohibited_term_audit_path: 已人工复核的驳回词候选 JSON 路径。
        prohibited_config_path: 本次审核使用的平台驳回词配置路径。
        visual_config: 已验证的视觉复核配置。
        completion_config: 已验证的完整审核校验配置。

    返回值：
        包含最终状态、分项统计和全部错误的汇总字典。
    """

    rows = load_inventory(inventory_path)
    visual_summary = validate_visual_review(inventory_path, visual_config)
    errors = [{"source": "visual", **item} for item in visual_summary.get("errors", [])]
    material_stats, material_errors = validate_material_reviews(
        rows,
        completion_config,
    )
    ad_stats, ad_errors = validate_ad_compliance_statuses(rows, completion_config)
    prohibited_stats, prohibited_errors = validate_prohibited_term_audit(
        inventory_path,
        rows,
        prohibited_term_audit_path,
        prohibited_config_path,
        completion_config,
    )
    errors.extend(material_errors)
    errors.extend(ad_errors)
    errors.extend(prohibited_errors)
    return {
        "schema_version": 1,
        "inventory": str(inventory_path.resolve()),
        "prohibited_term_audit": str(prohibited_term_audit_path.resolve()),
        "valid": not errors,
        "error_count": len(errors),
        "stats": {
            "visual": visual_summary.get("stats", {}),
            "material": material_stats,
            "ad_compliance": ad_stats,
            "prohibited_terms": prohibited_stats,
        },
        "errors": errors,
    }


def parse_args() -> argparse.Namespace:
    """解析命令行参数。

    参数：
        无。

    返回值：
        包含台账、驳回词结果、配置和汇总输出的参数对象。
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inventory", type=Path, help="已填写审核结果的 CSV 台账")
    parser.add_argument(
        "--prohibited-term-audit",
        type=Path,
        required=True,
        help="已人工复核的驳回词候选 JSON",
    )
    parser.add_argument(
        "--visual-config",
        type=Path,
        default=DEFAULT_VISUAL_CONFIG,
        help="视觉复核配置",
    )
    parser.add_argument(
        "--prohibited-config",
        type=Path,
        default=DEFAULT_PROHIBITED_CONFIG,
        help="平台驳回词配置",
    )
    parser.add_argument(
        "--completion-config",
        type=Path,
        default=DEFAULT_COMPLETION_CONFIG,
        help="完整审核校验配置",
    )
    parser.add_argument(
        "--summary-output", type=Path, required=True, help="校验汇总 JSON"
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="日志级别",
    )
    return parser.parse_args()


def main() -> int:
    """执行完整审核完成校验主流程。

    参数：
        无，参数从命令行读取。

    返回值：
        全部审核流程闭环时返回 0；存在遗漏或输入异常时返回 1。
    """

    args = parse_args()
    configure_logging(args.log_level)
    try:
        cleanup_work_directory(
            work_dir=DEFAULT_WORK_DIR,
            protected_paths=[
                args.inventory.parent,
                args.prohibited_term_audit.parent,
                args.summary_output.parent,
            ],
        )
        LOGGER.info("开始校验完整审核台账：%s", args.inventory.resolve())
        visual_config = load_visual_config(args.visual_config)
        completion_config = load_completion_config(args.completion_config)
        summary = validate_audit_completion(
            inventory_path=args.inventory,
            prohibited_term_audit_path=args.prohibited_term_audit,
            prohibited_config_path=args.prohibited_config,
            visual_config=visual_config,
            completion_config=completion_config,
        )
        args.summary_output.parent.mkdir(parents=True, exist_ok=True)
        args.summary_output.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if not summary["valid"]:
            LOGGER.error("完整审核校验未通过：%s 项", summary["error_count"])
            return 1
        LOGGER.info("完整审核校验通过：%s", summary["stats"])
        cleanup_work_directory(
            work_dir=DEFAULT_WORK_DIR,
            protected_paths=[
                args.inventory.parent,
                args.prohibited_term_audit.parent,
                args.summary_output.parent,
            ],
        )
    except Exception:
        LOGGER.exception("完整审核校验失败")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
