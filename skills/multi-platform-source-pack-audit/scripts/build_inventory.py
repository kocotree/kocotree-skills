#!/usr/bin/env python3
"""为多平台原始数据包质检生成只读文件台账。"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from cleanup_work import DEFAULT_WORK_DIR, cleanup_work_directory
from PIL import Image, UnidentifiedImageError

LOGGER = logging.getLogger("source_pack_inventory")
TYPOGRAPHY_CONFIG_PATH = (
    Path(__file__).resolve().parent.parent
    / "assets"
    / "configs"
    / "typography-profiles.json"
)
IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".bmp",
    ".gif",
    ".tif",
    ".tiff",
    ".avif",
}
FORMAT_EXTENSIONS = {
    "JPEG": {".jpg", ".jpeg"},
    "PNG": {".png"},
    "WEBP": {".webp"},
    "BMP": {".bmp"},
    "GIF": {".gif"},
    "TIFF": {".tif", ".tiff"},
    "AVIF": {".avif"},
}
IMAGE_AUDIT_FIELDS = [
    "identity_check_status",
    "visual_quality_status",
    "edge_alignment_status",
    "text_content_status",
    "typography_layout_status",
    "size_unit_status",
    "execution_standard_status",
    "logo_status",
    "color_consistency_status",
    "transparency_quality_status",
    "ad_compliance_status",
    "report_claim_status",
    "platform_size_status",
    "platform_file_size_status",
    "platform_quantity_naming_status",
    "platform_layout_status",
]
OCR_REVIEW_FIELDS = [
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
]
EDGE_REVIEW_FIELDS = [
    "edge_top_status",
    "edge_right_status",
    "edge_bottom_status",
    "edge_left_status",
    "internal_seam_status",
    "edge_review_notes",
    "edge_evidence_path",
]
TEXT_REVIEW_FIELDS = [
    "text_presence_status",
    "visible_text_transcript",
    "typo_status",
    "missing_extra_character_status",
    "grammar_status",
    "verb_collocation_status",
    "text_review_notes",
    "text_evidence_path",
]
MATERIAL_REVIEW_FIELDS = [
    "material_claim_presence_status",
    "material_claim_transcript",
    "material_reference_status",
    "material_reference_path",
    "material_reference_composition",
    "material_composition_status",
    "material_difference",
    "material_review_notes",
    "material_evidence_path",
]
TYPOGRAPHY_REVIEW_FIELDS = [
    "typography_profile_id",
    "typography_watch_characters",
    "watch_character_found_count",
    "watch_character_checked_count",
    "watch_character_abnormal_count",
    "watch_character_unreviewed_count",
    "typography_reference_status",
    "typography_occurrence_locations",
]
CSV_FIELDS = [
    "relative_path",
    "sku_or_style",
    "module",
    "platform",
    "extension",
    "bytes",
    "sha256",
    "duplicate_group",
    "is_symlink",
    "is_image",
    "width",
    "height",
    "dimension_key",
    "actual_format",
    "format_matches_extension",
    "mode",
    "has_alpha",
    "open_status",
    "open_error",
    "candidate_flags",
    "review_status",
    *OCR_REVIEW_FIELDS,
    *IMAGE_AUDIT_FIELDS,
    *EDGE_REVIEW_FIELDS,
    *TEXT_REVIEW_FIELDS,
    *MATERIAL_REVIEW_FIELDS,
    *TYPOGRAPHY_REVIEW_FIELDS,
    "non_image_readability_status",
    "issue_status",
    "severity",
    "issue_summary",
    "evidence_status",
    "evidence_path",
    "review_notes",
]


def load_typography_profiles(
    config_path: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """读取字体专项配置并记录资源可用性。

    参数：
        config_path: 字体专项 JSON 配置文件路径。

    返回值：
        字体专项配置列表，以及包含状态、错误和数量的资源汇总。
    """

    resolved_config = config_path.resolve()
    resource_summary: dict[str, Any] = {
        "status": "ready",
        "config_path": str(resolved_config),
        "errors": [],
        "profiles_total": 0,
        "profiles_ready": 0,
    }
    try:
        data = json.loads(resolved_config.read_text(encoding="utf-8"))
        raw_profiles = data.get("profiles")
        if not isinstance(raw_profiles, list):
            raise TypeError("字体专项配置中的 profiles 必须是列表")
        if not raw_profiles:
            raise ValueError("字体专项配置中的 profiles 不能为空")
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        error = f"字体专项配置无法读取：{type(exc).__name__}: {exc}"
        resource_summary["status"] = "unavailable"
        resource_summary["errors"].append(error)
        LOGGER.warning("%s；将继续生成其他台账内容", error)
        return [], resource_summary

    profiles: list[dict[str, Any]] = []
    resource_summary["profiles_total"] = len(raw_profiles)
    for index, raw_profile in enumerate(raw_profiles, start=1):
        if not isinstance(raw_profile, dict):
            error = f"字体专项配置第 {index} 项必须是对象"
            resource_summary["errors"].append(error)
            LOGGER.warning("%s；已跳过该项", error)
            continue
        profile = dict(raw_profile)
        required_fields = {
            "id",
            "scope_modules",
            "expected_font",
            "expected_weight",
            "font_asset",
            "reference_asset",
            "watch_characters",
        }
        missing_fields = sorted(required_fields - set(profile))
        if missing_fields:
            error = (
                f"字体专项配置 {profile.get('id', '<unknown>')} "
                f"缺少字段：{missing_fields}"
            )
            resource_summary["errors"].append(error)
            LOGGER.warning("%s；已跳过该项", error)
            continue

        profile_errors: list[str] = []
        asset_fields = (
            ("font_asset", "标准字体文件"),
            ("reference_asset", "标准字形参考图"),
        )
        for field, label in asset_fields:
            asset_path = (resolved_config.parent / str(profile[field])).resolve()
            if not asset_path.is_file():
                profile_errors.append(f"{label}不存在：{asset_path}")

        profile["_resource_status"] = "ready" if not profile_errors else "unavailable"
        profile["_resource_errors"] = profile_errors
        profiles.append(profile)
        if profile_errors:
            for error in profile_errors:
                resource_summary["errors"].append(error)
                LOGGER.warning("%s；该字体专项将标记为待补证", error)
        else:
            resource_summary["profiles_ready"] += 1

    if resource_summary["errors"]:
        resource_summary["status"] = (
            "partial" if resource_summary["profiles_ready"] else "unavailable"
        )
    LOGGER.info(
        "已加载字体专项配置：%s 个；资源状态=%s",
        len(profiles),
        resource_summary["status"],
    )
    return profiles, resource_summary


def match_typography_profile(
    relative_path: str,
    profiles: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """根据相对路径匹配适用的字体专项配置。

    参数：
        relative_path: 当前文件相对于原始数据包的路径。
        profiles: 已验证的字体专项配置列表。

    返回值：
        首个匹配的配置字典；没有匹配项时返回 None。
    """

    path_parts = [part.casefold() for part in Path(relative_path).parts]
    for profile in profiles:
        scopes = [str(scope).casefold() for scope in profile["scope_modules"]]
        if any(scope in part for scope in scopes for part in path_parts):
            return profile
    return None


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
    """计算文件的 SHA-256 哈希。

    参数：
        path: 需要计算哈希的文件路径。

    返回值：
        文件内容对应的十六进制 SHA-256 字符串。
    """

    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_image(path: Path, expected_image: bool) -> dict[str, str | int]:
    """读取图片属性并验证图片能否完整解码。

    参数：
        path: 待检查的文件路径。
        expected_image: 是否根据扩展名预期该文件为图片。

    返回值：
        包含尺寸、格式、颜色模式、Alpha 和打开状态的字典。
    """

    result: dict[str, str | int] = {
        "width": "",
        "height": "",
        "dimension_key": "",
        "actual_format": "",
        "format_matches_extension": "",
        "mode": "",
        "has_alpha": "",
        "open_status": "not_applicable",
        "open_error": "",
    }
    try:
        with Image.open(path) as image:
            image.load()
            actual_format = (image.format or "").upper()
            has_alpha = "A" in image.getbands() or "transparency" in image.info
            expected_extensions = FORMAT_EXTENSIONS.get(actual_format)
            format_matches = (
                path.suffix.lower() in expected_extensions
                if expected_extensions is not None
                else None
            )
            result.update(
                width=image.width,
                height=image.height,
                dimension_key=f"{image.width}x{image.height}",
                actual_format=actual_format,
                format_matches_extension=(
                    str(format_matches).lower()
                    if format_matches is not None
                    else "unknown"
                ),
                mode=image.mode,
                has_alpha=str(has_alpha).lower(),
                open_status="ok",
            )
    except UnidentifiedImageError as exc:
        if expected_image:
            result["open_status"] = "failed"
            result["open_error"] = f"{type(exc).__name__}: {exc}"
            LOGGER.warning("图片读取失败：%s；原因：%s", path, result["open_error"])
    except Exception as exc:  # noqa: BLE001  # 保留异常文件记录，避免台账漏项。
        result["open_status"] = "failed" if expected_image else "read_error"
        result["open_error"] = f"{type(exc).__name__}: {exc}"
        LOGGER.warning("文件内容识别失败：%s；原因：%s", path, result["open_error"])
    return result


def iter_files(root: Path, excluded_paths: set[Path]) -> Iterable[Path]:
    """按稳定顺序遍历根目录内的全部文件和文件链接。

    参数：
        root: 原始数据包根目录。
        excluded_paths: 不应写入台账的输出文件绝对路径集合。

    返回值：
        经过路径排序的文件迭代器。
    """

    paths = (
        path
        for path in root.rglob("*")
        if (path.is_file() or path.is_symlink())
        and path.resolve() not in excluded_paths
    )
    return iter(sorted(paths, key=lambda item: str(item).casefold()))


def inspect_directories(
    root: Path, excluded_paths: set[Path]
) -> tuple[list[str], list[str]]:
    """统计子目录并识别排除输出文件后的空目录。

    参数：
        root: 原始数据包根目录。
        excluded_paths: 盘点输出文件绝对路径集合。

    返回值：
        第一个列表为全部子目录相对路径，第二个列表为空目录相对路径。
    """

    directories: list[str] = []
    empty_directories: list[str] = []
    for directory in sorted(
        (item for item in root.rglob("*") if item.is_dir() and not item.is_symlink()),
        key=lambda item: str(item).casefold(),
    ):
        relative_path = directory.relative_to(root).as_posix()
        directories.append(relative_path)
        meaningful_children = [
            child
            for child in directory.iterdir()
            if child.resolve() not in excluded_paths
        ]
        if not meaningful_children:
            empty_directories.append(relative_path)
    return directories, empty_directories


def build_base_row(
    path: Path,
    root: Path,
    skip_hash: bool,
    typography_profiles: list[dict[str, Any]],
) -> dict[str, Any]:
    """读取单个文件并生成台账基础行。

    参数：
        path: 当前文件或文件链接路径。
        root: 原始数据包根目录。
        skip_hash: 是否跳过文件哈希计算。
        typography_profiles: 已验证的字体专项配置列表。

    返回值：
        包含文件属性和默认审核状态的台账字典。
    """

    relative_path = path.relative_to(root).as_posix()
    relative_parts = Path(relative_path).parts
    module = relative_parts[0] if len(relative_parts) > 1 else ""
    extension = path.suffix.lower()
    is_symlink = path.is_symlink()
    expected_image = extension in IMAGE_EXTENSIONS

    if is_symlink:
        image_data: dict[str, str | int] = {
            "width": "",
            "height": "",
            "dimension_key": "",
            "actual_format": "",
            "format_matches_extension": "",
            "mode": "",
            "has_alpha": "",
            "open_status": "symlink_not_followed",
            "open_error": "",
        }
        file_hash = ""
        file_size = ""
    else:
        image_data = inspect_image(path, expected_image)
        file_hash = "" if skip_hash else calculate_sha256(path)
        file_size = path.stat().st_size

    is_image = bool(image_data["actual_format"]) or expected_image
    image_default = "not_checked" if is_image else "not_applicable"
    typography_profile = (
        match_typography_profile(relative_path, typography_profiles)
        if is_image
        else None
    )
    typography_resources_ready = bool(
        typography_profile and typography_profile.get("_resource_status") == "ready"
    )
    candidate_flags: list[str] = []
    if image_data["open_status"] in {"failed", "read_error"}:
        candidate_flags.append("open_failure")
    if image_data["format_matches_extension"] == "false":
        candidate_flags.append("format_mismatch")
    if typography_profile and not typography_resources_ready:
        candidate_flags.append("typography_resource_unavailable")

    row: dict[str, Any] = {
        "relative_path": relative_path,
        "sku_or_style": "",
        "module": module,
        "platform": "",
        "extension": extension,
        "bytes": file_size,
        "sha256": file_hash,
        "duplicate_group": "",
        "is_symlink": str(is_symlink).lower(),
        "is_image": str(is_image).lower(),
        **image_data,
        "candidate_flags": ",".join(candidate_flags),
        "review_status": "not_checked",
        "ocr_status": image_default,
        "ocr_engine": "",
        "ocr_block_count": "",
        "ocr_mean_confidence": "",
        "ocr_low_confidence_count": "",
        "ocr_text": "",
        "ocr_review_scopes": "",
        "ocr_result_path": "",
        "ocr_evidence_path": "",
        "ocr_human_verified": "false" if is_image else "not_applicable",
        "ocr_review_notes": "",
        "typography_profile_id": (
            str(typography_profile["id"]) if typography_profile else ""
        ),
        "typography_watch_characters": (
            ",".join(str(item) for item in typography_profile["watch_characters"])
            if typography_profile
            else ""
        ),
        "watch_character_found_count": "",
        "watch_character_checked_count": "",
        "watch_character_abnormal_count": "",
        "watch_character_unreviewed_count": "",
        "typography_reference_status": (
            ("not_checked" if typography_resources_ready else "待补证")
            if typography_profile
            else "not_applicable"
        ),
        "typography_occurrence_locations": "",
        "edge_top_status": image_default,
        "edge_right_status": image_default,
        "edge_bottom_status": image_default,
        "edge_left_status": image_default,
        "internal_seam_status": "not_applicable",
        "edge_review_notes": "",
        "edge_evidence_path": "",
        "text_presence_status": image_default,
        "visible_text_transcript": "",
        "typo_status": image_default,
        "missing_extra_character_status": image_default,
        "grammar_status": image_default,
        "verb_collocation_status": image_default,
        "text_review_notes": "",
        "text_evidence_path": "",
        "material_claim_presence_status": image_default,
        "material_claim_transcript": "",
        "material_reference_status": image_default,
        "material_reference_path": "",
        "material_reference_composition": "",
        "material_composition_status": image_default,
        "material_difference": "",
        "material_review_notes": "",
        "material_evidence_path": "",
        "non_image_readability_status": (
            "not_applicable" if is_image else "not_checked"
        ),
        "issue_status": "",
        "severity": "",
        "issue_summary": "",
        "evidence_status": "not_required",
        "evidence_path": "",
        "review_notes": (
            "字体专项资源无法读取；详见汇总文件。"
            if typography_profile and not typography_resources_ready
            else ""
        ),
    }
    for field in IMAGE_AUDIT_FIELDS:
        row[field] = image_default
    return row


def assign_duplicate_groups(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """为相同哈希的文件写入稳定重复分组。

    参数：
        rows: 已完成基础属性读取的台账行。

    返回值：
        包含重复组编号、哈希和路径列表的分组信息。
    """

    paths_by_hash: dict[str, list[str]] = {}
    for row in rows:
        file_hash = str(row["sha256"])
        if file_hash:
            paths_by_hash.setdefault(file_hash, []).append(str(row["relative_path"]))

    duplicate_hashes = sorted(
        file_hash for file_hash, paths in paths_by_hash.items() if len(paths) > 1
    )
    group_by_hash = {
        file_hash: f"duplicate-{index:03d}"
        for index, file_hash in enumerate(duplicate_hashes, start=1)
    }
    for row in rows:
        file_hash = str(row["sha256"])
        group = group_by_hash.get(file_hash, "")
        row["duplicate_group"] = group
        if group:
            flags = [item for item in str(row["candidate_flags"]).split(",") if item]
            flags.append("duplicate_bytes")
            row["candidate_flags"] = ",".join(dict.fromkeys(flags))

    return [
        {
            "group": group_by_hash[file_hash],
            "sha256": file_hash,
            "paths": sorted(paths_by_hash[file_hash], key=str.casefold),
        }
        for file_hash in duplicate_hashes
    ]


def build_inventory(
    root: Path,
    output: Path,
    summary_output: Path | None,
    skip_hash: bool,
) -> dict[str, Any]:
    """扫描原始数据包并生成 CSV 台账和可选汇总文件。

    参数：
        root: 原始数据包根目录。
        output: CSV 台账输出路径。
        summary_output: JSON 汇总输出路径；为 None 时不输出 JSON。
        skip_hash: 是否跳过文件哈希计算。

    返回值：
        包含目录、文件、图片、损坏项和重复关系的汇总字典。
    """

    resolved_root = root.resolve()
    if not resolved_root.is_dir():
        raise NotADirectoryError(f"不是可访问目录：{resolved_root}")

    resolved_output = output.resolve()
    resolved_summary = summary_output.resolve() if summary_output else None
    excluded_paths = {resolved_output}
    if resolved_summary is not None:
        excluded_paths.add(resolved_summary)

    LOGGER.info("开始盘点原始数据包：%s", resolved_root)
    typography_profiles, typography_resource_summary = load_typography_profiles(
        TYPOGRAPHY_CONFIG_PATH
    )
    paths = list(iter_files(resolved_root, excluded_paths))
    directories, empty_directories = inspect_directories(resolved_root, excluded_paths)
    rows: list[dict[str, Any]] = []
    for index, path in enumerate(paths, start=1):
        row = build_base_row(path, resolved_root, skip_hash, typography_profiles)
        rows.append(row)
        LOGGER.info(
            "完成文件 %s/%s：%s；图片=%s；状态=%s",
            index,
            len(paths),
            row["relative_path"],
            row["is_image"],
            row["open_status"],
        )

    duplicate_groups = assign_duplicate_groups(rows)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8-sig") as target:
        writer = csv.DictWriter(target, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    counters: Counter[str] = Counter()
    dimensions: Counter[str] = Counter()
    broken_image_paths: list[str] = []
    format_mismatch_paths: list[str] = []
    symlink_paths: list[str] = []
    for row in rows:
        is_image = row["is_image"] == "true"
        counters["files"] += 1
        counters["images" if is_image else "other_files"] += 1
        if is_image and row["open_status"] == "failed":
            counters["broken_images"] += 1
            broken_image_paths.append(str(row["relative_path"]))
        if is_image and row["has_alpha"] == "true":
            counters["alpha_images"] += 1
        if is_image and row["format_matches_extension"] == "false":
            counters["format_mismatches"] += 1
            format_mismatch_paths.append(str(row["relative_path"]))
        if row["is_symlink"] == "true":
            counters["symlinks"] += 1
            symlink_paths.append(str(row["relative_path"]))
        if row["dimension_key"]:
            dimensions[str(row["dimension_key"])] += 1

    summary: dict[str, Any] = {
        "schema_version": 7,
        "root": str(resolved_root),
        "inventory": str(resolved_output),
        "directories": len(directories),
        "empty_directories": empty_directories,
        "empty_directory_count": len(empty_directories),
        "files": counters["files"],
        "images": counters["images"],
        "other_files": counters["other_files"],
        "broken_images": counters["broken_images"],
        "broken_image_paths": broken_image_paths,
        "alpha_images": counters["alpha_images"],
        "format_mismatches": counters["format_mismatches"],
        "format_mismatch_paths": format_mismatch_paths,
        "symlinks": counters["symlinks"],
        "symlink_paths": symlink_paths,
        "duplicate_hash_groups": len(duplicate_groups),
        "duplicate_groups": duplicate_groups,
        "image_dimensions": dict(sorted(dimensions.items(), key=lambda item: item[0])),
        "unreviewed_files": counters["files"],
        "unreviewed_images": counters["images"],
        "typography_resources": typography_resource_summary,
        "typography_profiles": [
            {
                "id": str(profile["id"]),
                "expected_font": str(profile["expected_font"]),
                "expected_weight": str(profile["expected_weight"]),
                "watch_characters": [str(item) for item in profile["watch_characters"]],
                "resource_status": str(profile["_resource_status"]),
                "resource_errors": [
                    str(error) for error in profile["_resource_errors"]
                ],
            }
            for profile in typography_profiles
        ],
        "typography_review_required_images": sum(
            1 for row in rows if row["typography_profile_id"]
        ),
        "typography_unreviewed_required_images": sum(
            1 for row in rows if row["typography_profile_id"]
        ),
        "hash_skipped": skip_hash,
    }
    if summary_output is not None:
        summary_output.parent.mkdir(parents=True, exist_ok=True)
        summary_output.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        LOGGER.info("已写入汇总文件：%s", summary_output.resolve())

    LOGGER.info(
        "盘点完成：目录=%s，空目录=%s，文件=%s，图片=%s，损坏图片=%s，重复组=%s",
        summary["directories"],
        summary["empty_directory_count"],
        summary["files"],
        summary["images"],
        summary["broken_images"],
        summary["duplicate_hash_groups"],
    )
    return summary


def parse_args() -> argparse.Namespace:
    """解析命令行参数。

    参数：
        无。

    返回值：
        包含原始包路径、输出路径和日志选项的参数对象。
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="需要盘点的原始数据包目录")
    parser.add_argument("--output", type=Path, required=True, help="CSV 台账输出路径")
    parser.add_argument("--summary-output", type=Path, help="JSON 汇总输出路径")
    parser.add_argument("--skip-hash", action="store_true", help="跳过 SHA-256 计算")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="日志级别",
    )
    return parser.parse_args()


def main() -> int:
    """执行原始数据包盘点主流程。

    参数：
        无，参数从命令行读取。

    返回值：
        成功返回 0；目录或文件处理失败时由异常触发非零退出码。
    """

    args = parse_args()
    configure_logging(args.log_level)
    try:
        cleanup_work_directory(work_dir=DEFAULT_WORK_DIR)
        build_inventory(
            root=args.root,
            output=args.output,
            summary_output=args.summary_output,
            skip_hash=args.skip_hash,
        )
    except Exception:
        LOGGER.exception("原始数据包盘点失败")
        return 1
    protected_paths = [args.output.parent]
    if args.summary_output is not None:
        protected_paths.append(args.summary_output.parent)
    cleanup_work_directory(
        work_dir=DEFAULT_WORK_DIR,
        protected_paths=protected_paths,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
