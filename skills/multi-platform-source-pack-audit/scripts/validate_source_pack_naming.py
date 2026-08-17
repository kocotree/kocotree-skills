#!/usr/bin/env python3
"""校验视觉部原始输入包的目录结构和文件命名。"""

from __future__ import annotations

import argparse
import json
import logging
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from cleanup_work import DEFAULT_WORK_DIR, cleanup_work_directory
from PIL import Image, UnidentifiedImageError

LOGGER = logging.getLogger("source_pack_naming")
DEFAULT_CONFIG_PATH = (
    Path(__file__).resolve().parent.parent
    / "assets"
    / "configs"
    / "source-pack-naming-rules.json"
)
CHECK_NAMES = {
    "root_name": "根目录款号与商品名称",
    "top_level_directories": "六类一级目录",
    "image_placement": "图片素材目录归属",
    "dimension_directory": "尺寸目录与实际像素",
    "color_filename": "颜色图片文件名",
    "color_correspondence": "白底图、透明底和 SKU 颜色对应",
    "transparent_png_alpha": "透明底 PNG 与 Alpha",
    "number_parsing": "主图、详情和素材图编号解析",
    "duplicate_and_unrecognized": "重名、重复编号和无法识别名称",
    "series_naming_consistency": "同一素材系列命名一致性",
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
    """读取并验证原始包命名配置。

    参数：
        config_path: 命名规则 JSON 文件路径。

    返回值：
        已完成基础字段校验的配置字典。
    """

    resolved_path = config_path.resolve()
    config = json.loads(resolved_path.read_text(encoding="utf-8"))
    required_fields = {
        "schema_version",
        "root_name_pattern",
        "required_top_level_directories",
        "image_extensions",
        "color_name_pattern",
        "disallowed_color_names",
        "color_modules",
        "module_rules",
    }
    missing_fields = sorted(required_fields - set(config))
    if missing_fields:
        raise ValueError(f"命名配置缺少字段：{missing_fields}")

    required_directories = config["required_top_level_directories"]
    module_rules = config["module_rules"]
    if not isinstance(required_directories, list) or not required_directories:
        raise ValueError("required_top_level_directories 必须是非空列表")
    if not isinstance(module_rules, dict):
        raise TypeError("module_rules 必须是对象")
    if set(required_directories) != set(module_rules):
        raise ValueError("一级目录清单必须与 module_rules 完全对应")

    re.compile(str(config["root_name_pattern"]))
    re.compile(str(config["color_name_pattern"]))
    for module, rule in module_rules.items():
        if "layout" not in rule or "filename_pattern" not in rule:
            raise ValueError(f"模块 {module} 缺少 layout 或 filename_pattern")
        re.compile(str(rule["filename_pattern"]))
        if "direct_filename_pattern" in rule:
            re.compile(str(rule["direct_filename_pattern"]))
    LOGGER.info("已加载原始包命名配置：%s", resolved_path)
    return config


def add_issue(
    issues: list[dict[str, str]],
    check_id: str,
    code: str,
    relative_path: str,
    actual: str,
    expected: str,
    message: str,
) -> None:
    """追加一个结构化命名问题。

    参数：
        issues: 当前任务的问题列表。
        check_id: 对应的十项检查编号。
        code: 稳定的问题代码。
        relative_path: 问题对象相对于输入包的路径。
        actual: 实际检测值。
        expected: 期望规则或值。
        message: 可直接写入报告的问题说明。

    返回值：
        无。
    """

    issue = {
        "check_id": check_id,
        "check_name": CHECK_NAMES[check_id],
        "code": code,
        "status": "已确认错误",
        "relative_path": relative_path,
        "actual": actual,
        "expected": expected,
        "message": message,
    }
    issues.append(issue)
    LOGGER.warning("命名问题：%s；路径=%s；实际=%s", code, relative_path, actual)


def parse_dimension_name(
    name: str,
    overrides: dict[str, list[int]],
) -> tuple[int, int] | None:
    """将尺寸目录或尺寸文件名解析为宽高。

    参数：
        name: 待解析的目录名或文件名主体。
        overrides: 当前模块的尺寸名称例外映射。

    返回值：
        解析成功时返回宽高元组，否则返回 None。
    """

    if name in overrides:
        values = overrides[name]
        if len(values) != 2:
            raise ValueError(f"尺寸覆盖值必须包含宽和高：{name}={values}")
        return int(values[0]), int(values[1])

    square_match = re.fullmatch(r"(\d+)", name)
    if square_match:
        edge = int(square_match.group(1))
        return edge, edge

    rectangle_match = re.fullmatch(r"(\d+)[-x×](\d+)", name)
    if rectangle_match:
        return int(rectangle_match.group(1)), int(rectangle_match.group(2))
    return None


def inspect_image_metadata(path: Path) -> dict[str, Any]:
    """读取图片真实格式、尺寸和透明通道。

    参数：
        path: 需要读取的图片路径。

    返回值：
        包含读取状态、格式、宽高和 Alpha 状态的字典。
    """

    try:
        with Image.open(path) as image:
            image.load()
            return {
                "read_status": "ok",
                "actual_format": (image.format or "").upper(),
                "width": image.width,
                "height": image.height,
                "has_alpha": "A" in image.getbands() or "transparency" in image.info,
                "error": "",
            }
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        LOGGER.warning("图片元数据读取失败：%s；原因：%s", path, exc)
        return {
            "read_status": "failed",
            "actual_format": "",
            "width": None,
            "height": None,
            "has_alpha": False,
            "error": f"{type(exc).__name__}: {exc}",
        }


def validate_root_and_directories(
    root: Path,
    config: dict[str, Any],
    issues: list[dict[str, str]],
) -> tuple[str, str, list[str], list[str]]:
    """检查根目录名称和六类一级目录。

    参数：
        root: 原始输入包根目录。
        config: 已加载的命名配置。
        issues: 当前任务的问题列表。

    返回值：
        款号、商品名称、缺失一级目录和非标准一级目录。
    """

    style_code = ""
    product_name = ""
    root_match = re.fullmatch(str(config["root_name_pattern"]), root.name)
    if root_match:
        style_code = root_match.groupdict().get("style_code", "")
        product_name = root_match.groupdict().get("product_name", "")
    else:
        add_issue(
            issues,
            "root_name",
            "invalid_root_name",
            ".",
            root.name,
            "{款号} {商品名称}",
            "根目录名称无法解析出款号和商品名称。",
        )

    expected = {str(item) for item in config["required_top_level_directories"]}
    actual = {item.name for item in root.iterdir() if item.is_dir()}
    missing = sorted(expected - actual, key=str.casefold)
    unexpected = sorted(actual - expected, key=str.casefold)
    for directory in missing:
        add_issue(
            issues,
            "top_level_directories",
            "missing_top_level_directory",
            directory,
            "缺失",
            directory,
            f"缺少一级素材目录“{directory}”。",
        )
    for directory in unexpected:
        add_issue(
            issues,
            "top_level_directories",
            "unexpected_top_level_directory",
            directory,
            directory,
            "、".join(sorted(expected, key=str.casefold)),
            f"一级目录“{directory}”不属于标准六类素材目录。",
        )
    return style_code, product_name, missing, unexpected


def expected_dimension_for_path(
    relative_parts: tuple[str, ...],
    stem: str,
    rule: dict[str, Any],
) -> tuple[int, int] | None:
    """根据模块布局计算图片应有尺寸。

    参数：
        relative_parts: 图片相对于输入包的路径组成部分。
        stem: 图片文件名主体。
        rule: 当前模块的命名配置。

    返回值：
        可解析时返回期望宽高，否则返回 None。
    """

    layout = str(rule["layout"])
    overrides = dict(rule.get("dimension_overrides", {}))
    if layout == "dimension_subdirectories" and len(relative_parts) == 3:
        return parse_dimension_name(relative_parts[1], overrides)
    if layout == "dimension_subdirectories_or_dimension_file":
        if len(relative_parts) == 3:
            return parse_dimension_name(relative_parts[1], overrides)
        if len(relative_parts) == 2:
            return parse_dimension_name(stem, overrides)
    return None


def validate_image_layout(
    path: Path,
    root: Path,
    config: dict[str, Any],
    issues: list[dict[str, str]],
    identifiers: dict[tuple[str, str], dict[str, list[str]]],
    normalized_names: dict[tuple[str, str], dict[str, list[str]]],
    series_extensions: dict[tuple[str, str], set[str]],
    color_sets: dict[str, set[str]],
) -> None:
    """检查单张图片的目录、尺寸、命名、编号和透明属性。

    参数：
        path: 当前图片路径。
        root: 原始输入包根目录。
        config: 已加载的命名配置。
        issues: 当前任务的问题列表。
        identifiers: 按素材系列收集的编号映射。
        normalized_names: 按目录收集的规范化文件名映射。
        series_extensions: 按素材系列收集的扩展名集合。
        color_sets: 白底图、透明底和 SKU 的颜色名称集合。

    返回值：
        无。
    """

    relative = path.relative_to(root)
    relative_path = relative.as_posix()
    parts = relative.parts
    module_rules = config["module_rules"]
    module = parts[0] if parts else ""
    if module not in module_rules:
        add_issue(
            issues,
            "image_placement",
            "image_outside_standard_module",
            relative_path,
            module or "根目录",
            "主图、SKU、白底图、透明底、详情或素材图",
            "图片未放入标准素材类型目录。",
        )
        return

    rule = module_rules[module]
    layout = str(rule["layout"])
    depth_valid = (
        (layout == "direct" and len(parts) == 2)
        or (layout == "dimension_subdirectories" and len(parts) == 3)
        or (
            layout == "dimension_subdirectories_or_dimension_file"
            and len(parts) in {2, 3}
        )
    )
    if not depth_valid:
        add_issue(
            issues,
            "image_placement",
            "invalid_module_path_depth",
            relative_path,
            "/".join(parts[:-1]) or ".",
            f"{module} 模块规定的 {layout} 布局",
            "图片所在层级不符合当前素材类型的目录结构。",
        )

    extension = path.suffix.casefold()
    series_key = (module, relative.parent.as_posix())
    series_extensions[series_key].add(extension)
    allowed_extensions = {str(item).casefold() for item in rule["extensions"]}
    if extension not in allowed_extensions:
        add_issue(
            issues,
            "series_naming_consistency",
            "invalid_series_extension",
            relative_path,
            extension or "无扩展名",
            "、".join(sorted(allowed_extensions)),
            "图片扩展名与当前素材系列的命名规则不一致。",
        )

    metadata = inspect_image_metadata(path)
    if metadata["read_status"] != "ok":
        add_issue(
            issues,
            "image_placement",
            "unreadable_image_metadata",
            relative_path,
            str(metadata["error"]),
            "可读取的图片文件",
            "无法读取图片真实格式、尺寸和透明属性。",
        )
        return

    stem = path.stem
    filename_pattern = str(rule["filename_pattern"])
    if layout == "dimension_subdirectories_or_dimension_file" and len(parts) == 2:
        filename_pattern = str(rule["direct_filename_pattern"])
    name_match = re.fullmatch(filename_pattern, stem)
    if not name_match:
        check_id = "color_filename" if rule.get("color_named") else "number_parsing"
        add_issue(
            issues,
            check_id,
            "unrecognized_filename",
            relative_path,
            path.name,
            filename_pattern,
            "文件名无法按当前素材类型的规则解析。",
        )
    else:
        identifier = str(name_match.groupdict().get("identifier", stem)).casefold()
        identifiers[series_key][identifier].append(relative_path)

    parent_key = (module, relative.parent.as_posix())
    normalized_names[parent_key][path.name.casefold()].append(relative_path)

    expected_dimension = expected_dimension_for_path(parts, stem, rule)
    if layout != "direct" and expected_dimension is None:
        dimension_source = parts[1] if len(parts) == 3 else stem
        add_issue(
            issues,
            "dimension_directory",
            "unrecognized_dimension_name",
            relative_path,
            dimension_source,
            "宽度、宽-高、宽x高或配置中的尺寸名称",
            "尺寸目录或尺寸文件名无法解析为真实宽高。",
        )
    elif expected_dimension is not None:
        actual_dimension = (int(metadata["width"]), int(metadata["height"]))
        if actual_dimension != expected_dimension:
            add_issue(
                issues,
                "dimension_directory",
                "dimension_name_mismatch",
                relative_path,
                f"{actual_dimension[0]}x{actual_dimension[1]}",
                f"{expected_dimension[0]}x{expected_dimension[1]}",
                "尺寸目录或尺寸文件名与图片实际像素不一致。",
            )

    if rule.get("color_named"):
        color_pattern = str(config["color_name_pattern"])
        disallowed = {str(item).casefold() for item in config["disallowed_color_names"]}
        if not re.fullmatch(color_pattern, stem) or stem.casefold() in disallowed:
            add_issue(
                issues,
                "color_filename",
                "invalid_color_filename",
                relative_path,
                path.stem,
                "具体商品颜色名称",
                "颜色图片未使用可识别的具体颜色名称。",
            )
        else:
            color_sets[module].add(stem.casefold())

    if rule.get("requires_png_alpha") and (
        metadata["actual_format"] != "PNG" or not metadata["has_alpha"]
    ):
        add_issue(
            issues,
            "transparent_png_alpha",
            "invalid_transparent_png",
            relative_path,
            f"格式={metadata['actual_format'] or '未知'}，Alpha={metadata['has_alpha']}",
            "PNG 且包含 Alpha 透明通道",
            "透明底图片必须使用带 Alpha 透明通道的 PNG。",
        )


def add_duplicate_issues(
    identifiers: dict[tuple[str, str], dict[str, list[str]]],
    normalized_names: dict[tuple[str, str], dict[str, list[str]]],
    issues: list[dict[str, str]],
) -> None:
    """根据收集结果写入重名和重复编号问题。

    参数：
        identifiers: 按素材系列收集的编号映射。
        normalized_names: 按目录收集的规范化文件名映射。
        issues: 当前任务的问题列表。

    返回值：
        无。
    """

    for (module, series), values in identifiers.items():
        for identifier, paths in values.items():
            if len(paths) > 1:
                add_issue(
                    issues,
                    "duplicate_and_unrecognized",
                    "duplicate_identifier",
                    series,
                    "、".join(paths),
                    "同一素材系列内编号唯一",
                    f"{module} 素材系列中编号“{identifier}”重复。",
                )
    for (_module, directory), values in normalized_names.items():
        for normalized_name, paths in values.items():
            if len(paths) > 1:
                add_issue(
                    issues,
                    "duplicate_and_unrecognized",
                    "duplicate_normalized_filename",
                    directory,
                    "、".join(paths),
                    "同一目录内文件名唯一",
                    f"规范化文件名“{normalized_name}”重复。",
                )


def add_series_consistency_issues(
    series_extensions: dict[tuple[str, str], set[str]],
    issues: list[dict[str, str]],
) -> None:
    """写入同一素材系列扩展名不一致问题。

    参数：
        series_extensions: 按素材系列收集的扩展名集合。
        issues: 当前任务的问题列表。

    返回值：
        无。
    """

    for (module, series), extensions in series_extensions.items():
        if len(extensions) > 1:
            add_issue(
                issues,
                "series_naming_consistency",
                "mixed_series_extensions",
                series,
                "、".join(sorted(extensions)),
                "同一素材系列使用一种扩展名",
                f"{module} 素材系列混用了多种图片扩展名。",
            )


def add_color_correspondence_issues(
    color_sets: dict[str, set[str]],
    config: dict[str, Any],
    issues: list[dict[str, str]],
) -> None:
    """检查三类颜色图片是否一一对应。

    参数：
        color_sets: 各颜色素材模块的文件名主体集合。
        config: 已加载的命名配置。
        issues: 当前任务的问题列表。

    返回值：
        无。
    """

    modules = [str(item) for item in config["color_modules"]]
    all_colors: set[str] = set()
    for module in modules:
        all_colors.update(color_sets[module])
    for module in modules:
        missing = sorted(all_colors - color_sets[module], key=str.casefold)
        if missing:
            add_issue(
                issues,
                "color_correspondence",
                "missing_color_counterpart",
                module,
                "缺少：" + "、".join(missing),
                "白底图、透明底和 SKU 颜色集合一致",
                f"{module} 缺少其他颜色素材中存在的颜色文件。",
            )


def build_check_results(issues: list[dict[str, str]]) -> list[dict[str, Any]]:
    """汇总十项命名检查的完成状态。

    参数：
        issues: 完整问题列表。

    返回值：
        包含每项检查名称、状态和问题数量的列表。
    """

    counts = Counter(issue["check_id"] for issue in issues)
    return [
        {
            "check_id": check_id,
            "check_name": check_name,
            "status": "不通过" if counts[check_id] else "通过",
            "issue_count": counts[check_id],
        }
        for check_id, check_name in CHECK_NAMES.items()
    ]


def validate_source_pack_naming(
    root: Path,
    config_path: Path,
    output: Path,
) -> dict[str, Any]:
    """执行原始输入包目录与文件命名质检并输出 JSON。

    参数：
        root: 原始输入包根目录。
        config_path: 命名规则 JSON 文件路径。
        output: 结构化质检结果 JSON 输出路径。

    返回值：
        包含十项检查状态、问题明细和颜色集合的汇总字典。
    """

    resolved_root = root.resolve()
    if not resolved_root.is_dir():
        raise NotADirectoryError(f"不是可访问目录：{resolved_root}")
    config = load_config(config_path)
    issues: list[dict[str, str]] = []
    LOGGER.info("开始检查原始包目录与文件命名：%s", resolved_root)
    style_code, product_name, missing_directories, unexpected_directories = (
        validate_root_and_directories(resolved_root, config, issues)
    )

    extensions = {str(item).casefold() for item in config["image_extensions"]}
    image_paths = sorted(
        (
            path
            for path in resolved_root.rglob("*")
            if path.is_file() and path.suffix.casefold() in extensions
        ),
        key=lambda item: str(item).casefold(),
    )
    identifiers: dict[tuple[str, str], dict[str, list[str]]] = defaultdict(
        lambda: defaultdict(list)
    )
    normalized_names: dict[tuple[str, str], dict[str, list[str]]] = defaultdict(
        lambda: defaultdict(list)
    )
    series_extensions: dict[tuple[str, str], set[str]] = defaultdict(set)
    color_sets: dict[str, set[str]] = defaultdict(set)
    for index, path in enumerate(image_paths, start=1):
        validate_image_layout(
            path,
            resolved_root,
            config,
            issues,
            identifiers,
            normalized_names,
            series_extensions,
            color_sets,
        )
        LOGGER.info("完成命名检查 %s/%s：%s", index, len(image_paths), path)

    add_duplicate_issues(identifiers, normalized_names, issues)
    add_series_consistency_issues(series_extensions, issues)
    add_color_correspondence_issues(color_sets, config, issues)
    check_results = build_check_results(issues)
    issue_counts = Counter(issue["code"] for issue in issues)
    summary: dict[str, Any] = {
        "schema_version": 1,
        "root": str(resolved_root),
        "style_code": style_code,
        "product_name": product_name,
        "image_count": len(image_paths),
        "passed": not issues,
        "issue_count": len(issues),
        "missing_top_level_directories": missing_directories,
        "unexpected_top_level_directories": unexpected_directories,
        "color_sets": {
            module: sorted(color_sets[module], key=str.casefold)
            for module in config["color_modules"]
        },
        "check_results": check_results,
        "issue_counts_by_code": dict(sorted(issue_counts.items())),
        "issues": issues,
    }
    resolved_output = output.resolve()
    resolved_output.parent.mkdir(parents=True, exist_ok=True)
    resolved_output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    LOGGER.info(
        "目录与命名检查完成：图片=%s，问题=%s，结果=%s",
        len(image_paths),
        len(issues),
        "通过" if not issues else "不通过",
    )
    LOGGER.info("已写入命名质检结果：%s", resolved_output)
    return summary


def parse_args() -> argparse.Namespace:
    """解析命令行参数。

    参数：
        无。

    返回值：
        包含输入包、配置、输出和日志选项的参数对象。
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="需要检查的原始输入包目录")
    parser.add_argument(
        "--output", type=Path, required=True, help="命名质检 JSON 输出路径"
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help="原始包命名规则 JSON 路径",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="日志级别",
    )
    return parser.parse_args()


def main() -> int:
    """执行原始输入包目录与命名质检主流程。

    参数：
        无，参数从命令行读取。

    返回值：
        扫描和结果写入成功返回 0，执行异常返回 1。
    """

    args = parse_args()
    configure_logging(args.log_level)
    try:
        cleanup_work_directory(work_dir=DEFAULT_WORK_DIR)
        validate_source_pack_naming(args.root, args.config, args.output)
        cleanup_work_directory(
            work_dir=DEFAULT_WORK_DIR,
            protected_paths=[args.output.resolve().parent],
        )
    except Exception:
        LOGGER.exception("原始输入包目录与命名质检失败")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
