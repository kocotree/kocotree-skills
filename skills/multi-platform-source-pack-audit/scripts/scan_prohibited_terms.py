#!/usr/bin/env python3
"""扫描质检台账中的可见文字并生成平台驳回词候选清单。"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any

from cleanup_work import DEFAULT_WORK_DIR, cleanup_work_directory

LOGGER = logging.getLogger("prohibited_term_scanner")
DEFAULT_CONFIG = (
    Path(__file__).resolve().parent.parent
    / "assets"
    / "configs"
    / "platform-prohibited-terms.json"
)
REQUIRED_INVENTORY_FIELDS = {
    "relative_path",
    "is_image",
    "text_presence_status",
    "visible_text_transcript",
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


def load_config(config_path: Path) -> dict[str, Any]:
    """读取并验证平台驳回词配置。

    参数：
        config_path: 平台驳回词 JSON 配置路径。

    返回值：
        包含平台列表和扫描规则的配置字典。
    """

    config = json.loads(config_path.resolve().read_text(encoding="utf-8"))
    platforms = config.get("platforms")
    rules = config.get("rules")
    if not isinstance(platforms, list) or not platforms:
        raise ValueError("平台驳回词配置 platforms 必须是非空列表")
    if not isinstance(rules, list) or not rules:
        raise ValueError("平台驳回词配置 rules 必须是非空列表")
    known_platforms = {str(item) for item in platforms}
    required_rule_fields = {
        "id",
        "platforms",
        "categories",
        "terms",
        "rule_type",
        "suggestion",
    }
    seen_ids: set[str] = set()
    for index, rule in enumerate(rules, start=1):
        if not isinstance(rule, dict):
            raise TypeError(f"平台驳回词配置第 {index} 条规则必须是对象")
        missing = sorted(required_rule_fields - set(rule))
        if missing:
            raise ValueError(f"平台驳回词规则第 {index} 条缺少字段：{missing}")
        rule_id = str(rule["id"])
        if rule_id in seen_ids:
            raise ValueError(f"平台驳回词规则 ID 重复：{rule_id}")
        seen_ids.add(rule_id)
        rule_platforms = {str(item) for item in rule["platforms"]}
        unknown_platforms = sorted(rule_platforms - known_platforms)
        if unknown_platforms:
            raise ValueError(
                f"平台驳回词规则 {rule_id} 包含未知平台：{unknown_platforms}"
            )
        for field in ("platforms", "categories", "terms"):
            if not isinstance(rule[field], list) or not rule[field]:
                raise ValueError(f"平台驳回词规则 {rule_id} 的 {field} 必须是非空列表")
    return config


def load_inventory(inventory_path: Path) -> list[dict[str, str]]:
    """读取并验证质检台账。

    参数：
        inventory_path: 包含文字转录的 CSV 台账路径。

    返回值：
        CSV 中的全部记录。
    """

    with inventory_path.resolve().open(newline="", encoding="utf-8-sig") as source:
        reader = csv.DictReader(source)
        fieldnames = set(reader.fieldnames or [])
        missing = sorted(REQUIRED_INVENTORY_FIELDS - fieldnames)
        if missing:
            raise ValueError(f"质检台账缺少驳回词扫描字段：{missing}")
        return list(reader)


def rule_applies(
    rule: dict[str, Any],
    platforms: set[str],
    categories: set[str],
) -> bool:
    """判断规则是否适用于当前平台和类目范围。"""

    rule_platforms = {str(item) for item in rule["platforms"]}
    rule_categories = {str(item).casefold() for item in rule["categories"]}
    platform_matches = not platforms or bool(rule_platforms & platforms)
    category_matches = (
        not categories or "*" in rule_categories or bool(rule_categories & categories)
    )
    return platform_matches and category_matches


def required_disposition(
    rule: dict[str, Any],
    platforms: set[str],
    categories: set[str],
) -> str:
    """根据任务范围和规则类型确定候选项所需处理状态。"""

    rule_categories = {str(item).casefold() for item in rule["categories"]}
    conditional_types = {"requires_evidence", "conditional", "context_review"}
    if not platforms:
        return "needs_evidence"
    if not categories and "*" not in rule_categories:
        return "needs_evidence"
    if str(rule["rule_type"]) in conditional_types:
        return "needs_evidence"
    return "issue"


def find_term_occurrences(text: str, terms: list[str]) -> list[dict[str, Any]]:
    """查找规则内不重叠的词语命中位置。"""

    occurrences: list[dict[str, Any]] = []
    occupied: list[tuple[int, int]] = []
    for term in sorted({str(item) for item in terms}, key=len, reverse=True):
        pattern = re.compile(re.escape(term), flags=re.IGNORECASE)
        for match in pattern.finditer(text):
            span = match.span()
            if any(span[0] < end and span[1] > start for start, end in occupied):
                continue
            occupied.append(span)
            occurrences.append(
                {
                    "term": match.group(0),
                    "start": span[0],
                    "end": span[1],
                }
            )
    return sorted(occurrences, key=lambda item: (item["start"], item["end"]))


def extract_context(text: str, start: int, end: int, radius: int = 24) -> str:
    """截取命中词前后的可读上下文。"""

    left = max(0, start - radius)
    right = min(len(text), end + radius)
    return text[left:right].replace("\r", " ").replace("\n", " ").strip()


def scan_inventory(
    inventory_path: Path,
    config: dict[str, Any],
    requested_platforms: list[str],
    requested_categories: list[str],
) -> dict[str, Any]:
    """扫描台账文字并生成可编辑的驳回词候选结果。

    参数：
        inventory_path: 包含逐图文字转录的 CSV 台账路径。
        config: 已验证的平台驳回词配置。
        requested_platforms: 本次任务明确适用的平台名称。
        requested_categories: 本次任务明确适用的商品类目。

    返回值：
        包含扫描范围、覆盖统计、候选命中和输入错误的字典。
    """

    known_platforms = {str(item) for item in config["platforms"]}
    platforms = {item.strip() for item in requested_platforms if item.strip()}
    unknown_platforms = sorted(platforms - known_platforms)
    if unknown_platforms:
        raise ValueError(f"存在未配置的平台：{unknown_platforms}")
    categories = {
        item.strip().casefold() for item in requested_categories if item.strip()
    }
    rows = load_inventory(inventory_path)
    applicable_rules = [
        rule for rule in config["rules"] if rule_applies(rule, platforms, categories)
    ]
    errors: list[dict[str, str]] = []
    unreadable_images: list[str] = []
    hits: list[dict[str, Any]] = []
    images_total = 0
    images_with_text = 0
    transcripts_scanned = 0
    for row_number, row in enumerate(rows, start=2):
        if row.get("is_image", "").strip().casefold() != "true":
            continue
        images_total += 1
        relative_path = row.get("relative_path", "").strip()
        presence = row.get("text_presence_status", "").strip()
        transcript = row.get("visible_text_transcript", "").strip()
        if presence == "present":
            images_with_text += 1
            if not transcript:
                errors.append(
                    {
                        "row": str(row_number),
                        "relative_path": relative_path,
                        "message": "含文字图片缺少可见文字转录",
                    }
                )
                continue
            transcripts_scanned += 1
        elif presence == "unreadable":
            unreadable_images.append(relative_path)
            continue
        elif presence == "absent":
            continue
        else:
            errors.append(
                {
                    "row": str(row_number),
                    "relative_path": relative_path,
                    "message": "图片文字存在性状态未完成",
                }
            )
            continue

        for rule in applicable_rules:
            occurrences = find_term_occurrences(
                transcript,
                [str(item) for item in rule["terms"]],
            )
            for occurrence in occurrences:
                matched_platforms = sorted(
                    {str(item) for item in rule["platforms"]}
                    & (platforms or known_platforms),
                    key=str.casefold,
                )
                existing = next(
                    (
                        item
                        for item in hits
                        if item["relative_path"] == relative_path
                        and item["start"] == occurrence["start"]
                        and item["end"] == occurrence["end"]
                        and str(item["term"]).casefold()
                        == str(occurrence["term"]).casefold()
                    ),
                    None,
                )
                disposition = required_disposition(rule, platforms, categories)
                if existing is not None:
                    existing["platforms"] = sorted(
                        set(existing["platforms"]) | set(matched_platforms),
                        key=str.casefold,
                    )
                    existing["matched_rule_ids"] = sorted(
                        set(existing["matched_rule_ids"]) | {str(rule["id"])},
                        key=str.casefold,
                    )
                    existing["suggestions"] = sorted(
                        set(existing["suggestions"]) | {str(rule["suggestion"])},
                        key=str.casefold,
                    )
                    if disposition == "issue":
                        existing["required_disposition"] = "issue"
                    continue
                hits.append(
                    {
                        "relative_path": relative_path,
                        "term": occurrence["term"],
                        "start": occurrence["start"],
                        "end": occurrence["end"],
                        "context": extract_context(
                            transcript,
                            int(occurrence["start"]),
                            int(occurrence["end"]),
                        ),
                        "platforms": matched_platforms,
                        "categories": [str(item) for item in rule["categories"]],
                        "matched_rule_ids": [str(rule["id"])],
                        "rule_type": str(rule["rule_type"]),
                        "suggestions": [str(rule["suggestion"])],
                        "required_disposition": disposition,
                        "review_status": "",
                        "review_notes": "",
                        "evidence_path": "",
                    }
                )

    for index, hit in enumerate(hits, start=1):
        hit["id"] = f"PT-{index:04d}"

    resolved_inventory = inventory_path.resolve()
    return {
        "schema_version": 1,
        "inventory": str(resolved_inventory),
        "text_input_sha256": calculate_text_input_sha256(rows),
        "scope_status": "specified" if platforms else "platform_unspecified",
        "platforms": sorted(platforms, key=str.casefold),
        "categories": sorted(categories),
        "scan_complete": not errors,
        "images_total": images_total,
        "images_with_text": images_with_text,
        "transcripts_scanned": transcripts_scanned,
        "unreadable_images": unreadable_images,
        "hit_count": len(hits),
        "hits": hits,
        "error_count": len(errors),
        "errors": errors,
    }


def parse_args() -> argparse.Namespace:
    """解析命令行参数。

    参数：
        无。

    返回值：
        包含台账、输出、配置和适用范围的参数对象。
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inventory", type=Path, help="包含文字转录的 CSV 台账")
    parser.add_argument("--output", type=Path, required=True, help="候选结果 JSON 路径")
    parser.add_argument(
        "--config", type=Path, default=DEFAULT_CONFIG, help="驳回词配置"
    )
    parser.add_argument(
        "--platform", action="append", default=[], help="适用平台，可重复"
    )
    parser.add_argument(
        "--category", action="append", default=[], help="商品类目，可重复"
    )
    parser.add_argument("--force", action="store_true", help="覆盖已有候选结果")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="日志级别",
    )
    return parser.parse_args()


def main() -> int:
    """执行平台驳回词扫描主流程。

    参数：
        无，参数从命令行读取。

    返回值：
        扫描完整时返回 0；输入、配置或文字覆盖不完整时返回 1。
    """

    args = parse_args()
    configure_logging(args.log_level)
    try:
        cleanup_work_directory(
            work_dir=DEFAULT_WORK_DIR,
            protected_paths=[args.inventory.parent, args.output.parent],
        )
        resolved_output = args.output.resolve()
        if resolved_output.exists() and not args.force:
            raise FileExistsError(
                f"候选结果已存在，使用 --force 才能覆盖：{resolved_output}"
            )
        LOGGER.info("开始扫描平台驳回词：%s", args.inventory.resolve())
        config = load_config(args.config)
        result = scan_inventory(
            inventory_path=args.inventory,
            config=config,
            requested_platforms=args.platform,
            requested_categories=args.category,
        )
        result["config"] = str(args.config.resolve())
        result["config_sha256"] = calculate_file_sha256(args.config.resolve())
        resolved_output.parent.mkdir(parents=True, exist_ok=True)
        resolved_output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if not result["scan_complete"]:
            LOGGER.error("平台驳回词扫描未完成：%s 项输入错误", result["error_count"])
            return 1
        LOGGER.info(
            "平台驳回词扫描完成：文字图片=%s，命中=%s",
            result["images_with_text"],
            result["hit_count"],
        )
        cleanup_work_directory(
            work_dir=DEFAULT_WORK_DIR,
            protected_paths=[args.inventory.parent, args.output.parent],
        )
    except Exception:
        LOGGER.exception("平台驳回词扫描失败")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
