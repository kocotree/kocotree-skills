#!/usr/bin/env python3
"""批量识别原始数据包图片文字并回填 OCR 审核字段。"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
import logging
import re
from pathlib import Path
from typing import Any

from cleanup_work import DEFAULT_WORK_DIR, cleanup_work_directory
from PIL import Image, ImageDraw, ImageOps
from rapidocr import RapidOCR

LOGGER = logging.getLogger("source_pack_ocr")
DEFAULT_CONFIG = (
    Path(__file__).resolve().parent.parent
    / "assets"
    / "configs"
    / "ocr-review-rules.json"
)
OCR_FIELDS = (
    "ocr_status",
    "ocr_engine",
    "ocr_block_count",
    "ocr_mean_confidence",
    "ocr_low_confidence_count",
    "ocr_text",
    "ocr_review_scopes",
    "ocr_result_path",
    "ocr_evidence_path",
    "ocr_human_verified",
    "ocr_review_notes",
)
REQUIRED_INVENTORY_FIELDS = {
    "relative_path",
    "module",
    "is_image",
    "sha256",
    "text_presence_status",
    "visible_text_transcript",
    *OCR_FIELDS,
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


def calculate_file_sha256(path: Path) -> str:
    """计算文件的 SHA-256 哈希。"""

    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def calculate_inventory_image_sha256(rows: list[dict[str, str]]) -> str:
    """计算图片路径和文件哈希组成的稳定摘要。"""

    payload = [
        {
            "relative_path": row.get("relative_path", ""),
            "is_image": row.get("is_image", ""),
            "sha256": row.get("sha256", ""),
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


def load_config(config_path: Path) -> dict[str, Any]:
    """读取并验证 OCR 审核配置。

    参数：
        config_path: OCR 审核 JSON 配置路径。

    返回值：
        包含引擎参数、置信度阈值和六类审核规则的配置字典。
    """

    config = json.loads(config_path.resolve().read_text(encoding="utf-8"))
    required = {
        "engine",
        "completed_ocr_statuses",
        "scope_status_fields",
        "scope_allowed_statuses",
        "scope_rules",
    }
    missing = sorted(required - set(config))
    if missing:
        raise ValueError(f"OCR 审核配置缺少字段：{missing}")
    engine = config["engine"]
    if not isinstance(engine, dict):
        raise TypeError("OCR 审核配置 engine 必须是对象")
    for field in (
        "name",
        "backend",
        "minimum_confidence",
        "evidence_max_side",
        "evidence_jpeg_quality",
    ):
        if field not in engine:
            raise ValueError(f"OCR 引擎配置缺少字段：{field}")
    minimum_confidence = float(engine["minimum_confidence"])
    if not 0 < minimum_confidence <= 1:
        raise ValueError("minimum_confidence 必须大于 0 且不大于 1")
    rules = config["scope_rules"]
    if not isinstance(rules, list) or not rules:
        raise ValueError("OCR 审核配置 scope_rules 必须是非空列表")
    scope_ids: set[str] = set()
    for index, rule in enumerate(rules, start=1):
        if not isinstance(rule, dict):
            raise TypeError(f"OCR 审核配置第 {index} 条范围规则必须是对象")
        rule_missing = sorted(
            {
                "id",
                "apply_to_all_text",
                "keywords",
                "patterns",
                "modules",
                "path_keywords",
            }
            - set(rule)
        )
        if rule_missing:
            raise ValueError(
                f"OCR 审核配置第 {index} 条范围规则缺少字段：{rule_missing}"
            )
        rule_id = str(rule["id"])
        if rule_id in scope_ids:
            raise ValueError(f"OCR 审核范围 ID 重复：{rule_id}")
        scope_ids.add(rule_id)
        for pattern in rule["patterns"]:
            re.compile(str(pattern))
    mapped_ids = {str(item) for item in config["scope_status_fields"]}
    if mapped_ids != scope_ids:
        raise ValueError("scope_status_fields 必须完整对应 scope_rules")
    allowed_ids = {str(item) for item in config["scope_allowed_statuses"]}
    if allowed_ids != scope_ids:
        raise ValueError("scope_allowed_statuses 必须完整对应 scope_rules")
    for scope_id, statuses in config["scope_allowed_statuses"].items():
        if not isinstance(statuses, list) or not statuses:
            raise ValueError(f"OCR 审核范围 {scope_id} 的允许状态必须是非空列表")
    return config


def load_inventory(
    inventory_path: Path,
) -> tuple[list[str], list[dict[str, str]]]:
    """读取并验证待回填的质检台账。

    参数：
        inventory_path: `build_inventory.py` 生成的 CSV 台账路径。

    返回值：
        CSV 字段顺序和全部台账记录。
    """

    with inventory_path.resolve().open(newline="", encoding="utf-8-sig") as source:
        reader = csv.DictReader(source)
        fieldnames = list(reader.fieldnames or [])
        missing = sorted(REQUIRED_INVENTORY_FIELDS - set(fieldnames))
        if missing:
            raise ValueError(f"质检台账缺少 OCR 字段，请重新建立台账：{missing}")
        return fieldnames, list(reader)


def resolve_image_path(package_root: Path, relative_path: str) -> Path:
    """解析并校验原始包图片路径没有越出商品根目录。"""

    resolved_root = package_root.resolve()
    candidate = (resolved_root / Path(relative_path)).resolve()
    if candidate != resolved_root and resolved_root not in candidate.parents:
        raise ValueError(f"图片路径越出原始包根目录：{relative_path}")
    if not candidate.is_file():
        raise FileNotFoundError(f"图片文件不存在：{candidate}")
    return candidate


def detect_review_scopes(
    text: str,
    module: str,
    relative_path: str,
    config: dict[str, Any],
) -> list[str]:
    """根据 OCR 全文生成六类文字审核候选范围。

    参数：
        text: 当前图片的 OCR 全文。
        module: 当前图片在台账中的素材模块。
        relative_path: 当前图片相对原始包根目录的路径。
        config: 已验证的 OCR 审核配置。

    返回值：
        按配置顺序排列的审核范围 ID。
    """

    scopes: list[str] = []
    folded_module = module.casefold()
    folded_path = relative_path.casefold()
    for rule in config["scope_rules"]:
        applies = bool(rule["apply_to_all_text"]) and bool(text)
        if not applies:
            applies = any(
                str(keyword).casefold() in text.casefold()
                for keyword in rule["keywords"]
            )
        if not applies:
            applies = any(re.search(str(pattern), text) for pattern in rule["patterns"])
        if not applies:
            applies = any(
                folded_module == str(configured_module).casefold()
                for configured_module in rule["modules"]
            )
        if not applies:
            applies = any(
                str(keyword).casefold() in folded_path
                for keyword in rule["path_keywords"]
            )
        if applies:
            scopes.append(str(rule["id"]))
    return scopes


def normalize_blocks(result: Any, minimum_confidence: float) -> list[dict[str, Any]]:
    """将 RapidOCR 输出转换为可序列化文字块。

    参数：
        result: RapidOCR 返回的识别对象。
        minimum_confidence: 低置信度判定阈值。

    返回值：
        包含序号、文字、置信度、四点坐标和低置信度标记的列表。
    """

    texts = tuple(result.txts or ())
    scores = tuple(result.scores or ())
    boxes = result.boxes.tolist() if result.boxes is not None else []
    if not (len(texts) == len(scores) == len(boxes)):
        raise ValueError("RapidOCR 返回的文字、置信度和坐标数量不一致")
    blocks: list[dict[str, Any]] = []
    for index, (text, score, box) in enumerate(zip(texts, scores, boxes), start=1):
        numeric_score = float(score)
        blocks.append(
            {
                "index": index,
                "text": str(text),
                "confidence": round(numeric_score, 6),
                "low_confidence": numeric_score < minimum_confidence,
                "polygon": [
                    [round(float(point[0]), 2), round(float(point[1]), 2)]
                    for point in box
                ],
            }
        )
    return blocks


def create_evidence_image(
    image_path: Path,
    blocks: list[dict[str, Any]],
    output_path: Path,
    config: dict[str, Any],
) -> None:
    """生成带文字框序号和置信度的 OCR 复核图。

    参数：
        image_path: 原始图片路径。
        blocks: 当前图片的 OCR 文字块列表。
        output_path: 复核图输出路径。
        config: 已验证的 OCR 审核配置。

    返回值：
        无。
    """

    engine_config = config["engine"]
    minimum_confidence = float(engine_config["minimum_confidence"])
    max_side = int(engine_config["evidence_max_side"])
    quality = int(engine_config["evidence_jpeg_quality"])
    with Image.open(image_path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
    scale = min(1.0, max_side / max(image.size))
    if scale < 1.0:
        image = image.resize(
            (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
            Image.Resampling.LANCZOS,
        )
    draw = ImageDraw.Draw(image)
    line_width = max(2, round(min(image.size) / 500))
    for block in blocks:
        polygon = [
            (round(float(point[0]) * scale), round(float(point[1]) * scale))
            for point in block["polygon"]
        ]
        color = (
            "#e53935" if float(block["confidence"]) < minimum_confidence else "#00a6a6"
        )
        draw.line(polygon + [polygon[0]], fill=color, width=line_width)
        left = min(point[0] for point in polygon)
        top = min(point[1] for point in polygon)
        label = f"#{block['index']} {float(block['confidence']):.2f}"
        label_box = draw.textbbox((left, top), label)
        draw.rectangle(label_box, fill="#ffffff")
        draw.text((left, top), label, fill=color)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, format="JPEG", quality=quality, optimize=True)


def build_evidence_path(evidence_dir: Path, index: int, relative_path: str) -> Path:
    """生成稳定且适合 Windows 的 OCR 复核图文件名。"""

    stem = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]+", "-", Path(relative_path).stem)
    safe_stem = stem.strip("-")[:48] or "image"
    return evidence_dir.resolve() / f"{index:04d}-{safe_stem}-ocr.jpg"


def write_inventory(
    inventory_path: Path,
    fieldnames: list[str],
    rows: list[dict[str, str]],
) -> None:
    """以原子替换方式写回工作目录台账。

    参数：
        inventory_path: 需要更新的 CSV 台账路径。
        fieldnames: 原台账字段顺序。
        rows: 已回填 OCR 字段的全部记录。

    返回值：
        无。
    """

    resolved = inventory_path.resolve()
    temporary = resolved.with_suffix(f"{resolved.suffix}.ocr.tmp")
    with temporary.open("w", newline="", encoding="utf-8-sig") as target:
        writer = csv.DictWriter(target, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(resolved)


def run_ocr(
    package_root: Path,
    inventory_path: Path,
    results_output: Path,
    evidence_dir: Path,
    config_path: Path,
    force: bool,
) -> dict[str, Any]:
    """执行全包 OCR 并回填台账。

    参数：
        package_root: 只读原始数据包根目录。
        inventory_path: 工作目录中的 CSV 台账路径。
        results_output: OCR 结构化结果 JSON 输出路径。
        evidence_dir: OCR 复核图输出目录。
        config_path: OCR 范围与阈值配置路径。
        force: 是否覆盖已有 OCR 结果。

    返回值：
        包含引擎版本、覆盖统计、逐图文字块和错误的汇总字典。
    """

    config = load_config(config_path)
    fieldnames, rows = load_inventory(inventory_path)
    resolved_results = results_output.resolve()
    if resolved_results.exists() and not force:
        raise FileExistsError(
            f"OCR 结果已存在，使用 --force 才能覆盖：{resolved_results}"
        )
    image_rows = [
        row for row in rows if row.get("is_image", "").strip().casefold() == "true"
    ]
    if not force:
        completed = [
            row.get("relative_path", "")
            for row in image_rows
            if row.get("ocr_status", "").strip() not in {"", "not_checked"}
        ]
        if completed:
            raise ValueError(
                f"台账已有 OCR 结果，使用 --force 才能覆盖：{completed[:5]}"
            )

    rapidocr_version = importlib.metadata.version("rapidocr")
    onnxruntime_version = importlib.metadata.version("onnxruntime")
    engine_label = f"RapidOCR {rapidocr_version} / onnxruntime {onnxruntime_version}"
    minimum_confidence = float(config["engine"]["minimum_confidence"])
    LOGGER.info("加载 OCR 引擎：%s", engine_label)
    engine = RapidOCR()
    images: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    success_count = 0
    no_text_count = 0
    failed_count = 0
    low_confidence_blocks = 0

    for image_index, row in enumerate(image_rows, start=1):
        relative_path = row.get("relative_path", "").strip()
        image_id = f"OCR-{image_index:05d}"
        evidence_path = build_evidence_path(evidence_dir, image_index, relative_path)
        LOGGER.info("OCR %s/%s：%s", image_index, len(image_rows), relative_path)
        try:
            image_path = resolve_image_path(package_root, relative_path)
            result = engine(str(image_path))
            blocks = normalize_blocks(result, minimum_confidence)
            text = "\n".join(str(block["text"]) for block in blocks)
            scopes = detect_review_scopes(
                text,
                row.get("module", "").strip(),
                relative_path,
                config,
            )
            scores = [float(block["confidence"]) for block in blocks]
            mean_confidence = sum(scores) / len(scores) if scores else None
            low_count = sum(bool(block["low_confidence"]) for block in blocks)
            status = "success" if blocks else "no_text"
            create_evidence_image(image_path, blocks, evidence_path, config)
            row.update(
                {
                    "ocr_status": status,
                    "ocr_engine": engine_label,
                    "ocr_block_count": str(len(blocks)),
                    "ocr_mean_confidence": (
                        f"{mean_confidence:.6f}" if mean_confidence is not None else ""
                    ),
                    "ocr_low_confidence_count": str(low_count),
                    "ocr_text": text,
                    "ocr_review_scopes": ";".join(scopes),
                    "ocr_result_path": f"{resolved_results}#{image_id}",
                    "ocr_evidence_path": str(evidence_path),
                    "ocr_human_verified": "false",
                    "ocr_review_notes": "",
                }
            )
            if row.get("text_presence_status", "").strip() in {"", "not_checked"}:
                row["text_presence_status"] = "present" if blocks else "absent"
                row["visible_text_transcript"] = text
            images.append(
                {
                    "id": image_id,
                    "relative_path": relative_path,
                    "sha256": row.get("sha256", ""),
                    "status": status,
                    "text": text,
                    "block_count": len(blocks),
                    "mean_confidence": (
                        round(mean_confidence, 6)
                        if mean_confidence is not None
                        else None
                    ),
                    "low_confidence_count": low_count,
                    "review_scopes": scopes,
                    "evidence_path": str(evidence_path),
                    "blocks": blocks,
                }
            )
            low_confidence_blocks += low_count
            if blocks:
                success_count += 1
            else:
                no_text_count += 1
            LOGGER.info(
                "OCR 完成：%s；文字块=%s；低置信度=%s；范围=%s",
                relative_path,
                len(blocks),
                low_count,
                scopes,
            )
        except Exception as exc:  # noqa: BLE001  # 单图失败后继续处理全包。
            failed_count += 1
            message = f"{type(exc).__name__}: {exc}"
            row.update(
                {
                    "ocr_status": "failed",
                    "ocr_engine": engine_label,
                    "ocr_block_count": "",
                    "ocr_mean_confidence": "",
                    "ocr_low_confidence_count": "",
                    "ocr_text": "",
                    "ocr_review_scopes": "",
                    "ocr_result_path": f"{resolved_results}#{image_id}",
                    "ocr_evidence_path": "",
                    "ocr_human_verified": "false",
                    "ocr_review_notes": message,
                }
            )
            errors.append({"relative_path": relative_path, "message": message})
            images.append(
                {
                    "id": image_id,
                    "relative_path": relative_path,
                    "sha256": row.get("sha256", ""),
                    "status": "failed",
                    "error": message,
                    "blocks": [],
                }
            )
            LOGGER.warning("OCR 失败：%s；原因：%s", relative_path, message)

    summary = {
        "schema_version": 1,
        "package_root": str(package_root.resolve()),
        "inventory": str(inventory_path.resolve()),
        "inventory_image_sha256": calculate_inventory_image_sha256(rows),
        "config": str(config_path.resolve()),
        "config_sha256": calculate_file_sha256(config_path.resolve()),
        "engine": {
            "name": "RapidOCR",
            "version": rapidocr_version,
            "backend": "onnxruntime",
            "backend_version": onnxruntime_version,
            "minimum_confidence": minimum_confidence,
        },
        "scan_complete": failed_count == 0,
        "images_total": len(image_rows),
        "success_count": success_count,
        "no_text_count": no_text_count,
        "failed_count": failed_count,
        "low_confidence_block_count": low_confidence_blocks,
        "images": images,
        "errors": errors,
    }
    resolved_results.parent.mkdir(parents=True, exist_ok=True)
    resolved_results.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_inventory(inventory_path, fieldnames, rows)
    return summary


def parse_args() -> argparse.Namespace:
    """解析命令行参数。

    参数：
        无。

    返回值：
        包含原始包、台账、结果、证据目录和配置的参数对象。
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package_root", type=Path, help="只读原始数据包根目录")
    parser.add_argument("inventory", type=Path, help="工作目录中的 CSV 台账")
    parser.add_argument(
        "--results-output", type=Path, required=True, help="OCR 结构化结果 JSON"
    )
    parser.add_argument(
        "--evidence-dir", type=Path, required=True, help="OCR 复核图输出目录"
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="OCR 配置")
    parser.add_argument("--force", action="store_true", help="覆盖已有 OCR 结果")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="日志级别",
    )
    return parser.parse_args()


def main() -> int:
    """执行批量 OCR 主流程。

    参数：
        无，参数从命令行读取。

    返回值：
        全部图片完成 OCR 时返回 0；存在单图失败或输入异常时返回 1。
    """

    args = parse_args()
    configure_logging(args.log_level)
    try:
        cleanup_work_directory(
            work_dir=DEFAULT_WORK_DIR,
            protected_paths=[
                args.inventory.parent,
                args.results_output.parent,
                args.evidence_dir,
            ],
        )
        LOGGER.info("开始全包 OCR：%s", args.package_root.resolve())
        summary = run_ocr(
            package_root=args.package_root,
            inventory_path=args.inventory,
            results_output=args.results_output,
            evidence_dir=args.evidence_dir,
            config_path=args.config,
            force=args.force,
        )
        LOGGER.info(
            "全包 OCR 完成：图片=%s；有文字=%s；无文字=%s；失败=%s",
            summary["images_total"],
            summary["success_count"],
            summary["no_text_count"],
            summary["failed_count"],
        )
        cleanup_work_directory(
            work_dir=DEFAULT_WORK_DIR,
            protected_paths=[
                args.inventory.parent,
                args.results_output.parent,
                args.evidence_dir,
            ],
        )
        return 0 if summary["scan_complete"] else 1
    except Exception:
        LOGGER.exception("全包 OCR 失败")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
