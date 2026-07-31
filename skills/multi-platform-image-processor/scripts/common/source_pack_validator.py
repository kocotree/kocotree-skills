from __future__ import annotations

import json
import logging
from collections import deque
from pathlib import Path, PurePosixPath
from typing import Any

from PIL import Image

from .scan_source_pack import resolve_sku_root, resolve_source_path
from .transparent_issue_visualizer import render_transparent_issue, render_transparent_overview
from .utils import list_images


logger = logging.getLogger(__name__)

必需图片目录 = ("主图800", "主图750", "SKU800", "白底图", "透明图")
可选图片目录 = ("主图1440", "SKU1440")
主图错误目录 = {
    "800主图": "800",
    "750 1000主图": "750",
    "750主图": "750",
    "1440主图": "1440",
}
透明图规则文件名 = "透明图规则.json"
透明可见阈值 = 8
明确主体最小面积比例 = 0.02
细长主体最小面积比例 = 0.002
明确主体最小长边比例 = 0.15
明确脏点最大像素数 = 4
明确脏点最大面积比例 = 0.001
明确脏点最大长边比例 = 0.05

标准输入结构 = """产品名称/
└─ 数据包/
   ├─ 主图/
   │  ├─ 800/
   │  │  ├─ 1.jpg
   │  │  ├─ 2.jpg
   │  │  └─ ...
   │  ├─ 1440/
   │  │  ├─ 1.jpg
   │  │  ├─ 2.jpg
   │  │  └─ ...
   │  └─ 750/
   │     ├─ 1.jpg
   │     ├─ 2.jpg
   │     └─ ...
   │
   ├─ SKU/
   │  ├─ 800/
   │  │  ├─ 颜色名.jpg
   │  │  └─ ...
   │  └─ 1440/
   │     ├─ 颜色名.jpg
   │     └─ ...
   │
   ├─ 白底图/
   │  ├─ 颜色名.jpg
   │  └─ ...
   │
   ├─ 透明图/
   │  ├─ 颜色名.png
   │  └─ ...
   │
   ├─ 详情/
   │  └─ 静态/
   │     ├─ 1.jpg
   │     ├─ 2.jpg
   │     └─ ...
   │
   └─ 素材图/
      ├─ 图片.jpg
      ├─ 子目录/
      │  └─ 图片.jpg
      └─ ...

详情页结构二选一，禁止混用：

方案一：平铺结构
详情/静态/
├─ 1.jpg
├─ 2.jpg
└─ ...

方案二：上/下结构
详情/静态/
├─ 上/
│  ├─ 1.jpg
│  └─ ...
└─ 下/
   ├─ 1.jpg
   └─ ..."""


def validate_source_pack(
    source_root: Path,
    visualization_dir: Path | None = None,
) -> dict[str, Any]:
    """强制检查标准输入文件夹结构和透明图独立区域。

    功能说明：检查标准目录名称、必需目录是否存在且包含图片，并检查每张
    透明 PNG 是否具有透明通道，区分主体组成部分、待确认区域和脏点。

    参数：
        source_root：待处理的数据包根目录。
        visualization_dir：透明图独立区域诊断图输出目录；未提供时只返回坐标数据。
    返回值：
        包含“通过”“问题”“警告”和“识别目录”的结构化检测结果。
    """
    problems: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    recognized: dict[str, dict[str, Any]] = {}
    logger.info("开始强制检测输入包结构和透明图：%s", source_root)

    if not source_root.is_dir():
        _add_problem(problems, "数据包目录不存在", source_root)
        return _result(problems, warnings, recognized)

    _check_misnamed_main_directories(source_root, problems)
    _check_sku_root(source_root, problems, recognized)

    for key in 必需图片目录:
        _check_image_directory(
            source_root,
            key,
            required=True,
            problems=problems,
            recognized=recognized,
        )
    for key in 可选图片目录:
        _check_image_directory(
            source_root,
            key,
            required=False,
            problems=problems,
            recognized=recognized,
        )

    _check_detail_directory(source_root, problems, recognized)
    _check_optional_material_directory(source_root, warnings, recognized)

    diagnostic_paths = []
    transparent_path = resolve_source_path(source_root, "透明图")
    transparent_images = list_images(transparent_path)
    component_rules = _load_transparent_component_rules(transparent_path, problems)
    matched_rules: set[str] = set()
    for image_path in transparent_images:
        relative_name = image_path.relative_to(transparent_path).as_posix()
        allowed_subject_count = component_rules.get(relative_name)
        if allowed_subject_count is not None:
            matched_rules.add(relative_name)
        diagnostic_path = _check_transparent_image(
            image_path,
            problems,
            warnings,
            visualization_dir,
            allowed_subject_count,
        )
        if diagnostic_path:
            diagnostic_paths.append(diagnostic_path)
    for unmatched_rule in sorted(set(component_rules) - matched_rules):
        warnings.append({
            "信息": "透明图规则没有匹配到图片",
            "规则文件": str(transparent_path / 透明图规则文件名),
            "图片": unmatched_rule,
        })

    result = _result(problems, warnings, recognized)
    if diagnostic_paths:
        result["透明图诊断图"] = [str(path) for path in diagnostic_paths]
        overview = render_transparent_overview(diagnostic_paths, visualization_dir or diagnostic_paths[0].parent)
        if overview:
            result["透明图问题汇总"] = str(overview)
    if result["通过"]:
        logger.info("输入包结构和透明图检测通过：%s", source_root)
    else:
        logger.error("输入包检测失败：%s，共%d项问题", source_root, len(problems))
    return result


def _check_misnamed_main_directories(source_root: Path, problems: list[dict[str, Any]]) -> None:
    main_root = source_root / "主图"
    if not main_root.is_dir():
        _add_problem(problems, "缺少必需目录：主图", main_root)
        return
    for wrong_name, standard_name in 主图错误目录.items():
        wrong_path = main_root / wrong_name
        if wrong_path.exists():
            _add_problem(
                problems,
                f"主图目录名称不标准：主图\\{wrong_name}",
                wrong_path,
                f"请改为 主图\\{standard_name}",
            )


def _check_sku_root(
    source_root: Path,
    problems: list[dict[str, Any]],
    recognized: dict[str, dict[str, Any]],
) -> None:
    matches = [
        child for child in source_root.iterdir()
        if child.is_dir() and child.name.casefold() == "sku"
    ]
    if not matches:
        _add_problem(problems, "缺少必需目录：SKU（大小写不限）", source_root / "SKU")
        return
    if len(matches) > 1:
        _add_problem(
            problems,
            "存在多个仅大小写不同的 SKU 目录",
            source_root,
            "只保留一个 SKU、sku 或其他大小写形式的目录",
        )
        return
    sku_root = resolve_sku_root(source_root)
    recognized["SKU"] = {"目录": str(sku_root), "实际名称": sku_root.name}


def _check_image_directory(
    source_root: Path,
    key: str,
    required: bool,
    problems: list[dict[str, Any]],
    recognized: dict[str, dict[str, Any]],
) -> None:
    path = resolve_source_path(source_root, key)
    if not path.is_dir():
        if required:
            _add_problem(problems, f"缺少必需目录：{_display_path(source_root, path)}", path)
        return
    images = list_images(path)
    recognized[key] = {"目录": str(path), "图片数量": len(images)}
    if not images:
        message = "必需目录没有图片" if required else "可选目录存在但没有图片"
        _add_problem(problems, f"{message}：{_display_path(source_root, path)}", path)


def _check_detail_directory(
    source_root: Path,
    problems: list[dict[str, Any]],
    recognized: dict[str, dict[str, Any]],
) -> None:
    """检查详情页是否使用唯一且完整的标准结构。

    功能说明：详情页可使用静态目录平铺图片，或使用非空的“上/下”
    两个子目录；两种结构互斥。

    参数：
        source_root：待检测的数据包根目录。
        problems：用于追加结构问题的列表。
        recognized：用于记录实际识别目录和详情模式的字典。
    返回值：
        无返回值。
    """
    static_root = resolve_source_path(source_root, "详情静态")
    if not static_root.is_dir():
        _add_problem(problems, "缺少必需目录：详情\\静态", static_root)
        return

    upper_path = resolve_source_path(source_root, "详情上")
    lower_path = resolve_source_path(source_root, "详情下")
    invalid_nodes = [
        path for path in (upper_path, lower_path)
        if path.exists() and not path.is_dir()
    ]
    if invalid_nodes:
        recognized["详情静态"] = {
            "目录": str(static_root),
            "模式": "无效",
            "直接图片数量": len(list_images(static_root)),
            "上部图片数量": 0,
            "下部图片数量": 0,
        }
        for path in invalid_nodes:
            _add_problem(
                problems,
                f"详情页结构无效：{_display_path(source_root, path)} 必须是目录",
                path,
            )
        logger.warning(
            "详情页结构检测失败：上/下节点不是目录 paths=%r",
            [str(path) for path in invalid_nodes],
            extra={
                "stage": "输入检测",
                "event": "详情结构检测",
                "status": "failed",
            },
        )
        return

    direct_images = list_images(static_root)
    upper_exists = upper_path.is_dir()
    lower_exists = lower_path.is_dir()
    upper_images = list_images(upper_path) if upper_exists else []
    lower_images = list_images(lower_path) if lower_exists else []
    recognized["详情静态"] = {
        "目录": str(static_root),
        "模式": "未识别",
        "直接图片数量": len(direct_images),
        "上部图片数量": len(upper_images),
        "下部图片数量": len(lower_images),
    }

    if direct_images and not upper_exists and not lower_exists:
        recognized["详情静态"]["模式"] = "平铺"
        logger.info(
            "详情页结构检测通过 mode=flat direct_count=%d",
            len(direct_images),
            extra={
                "stage": "输入检测",
                "event": "详情结构检测",
                "status": "success",
            },
        )
        return

    if direct_images and (upper_exists or lower_exists):
        recognized["详情静态"]["模式"] = "混合结构"
        _add_problem(
            problems,
            "详情页结构混用：平铺图片不能与详情\\静态\\上或详情\\静态\\下同时存在",
            static_root,
            "保留平铺图片，或移除平铺图片并同时提供非空的上、下目录",
        )
        logger.warning(
            "详情页结构检测失败：平铺与上/下结构混用 direct_count=%d upper_count=%d lower_count=%d",
            len(direct_images),
            len(upper_images),
            len(lower_images),
            extra={
                "stage": "输入检测",
                "event": "详情结构检测",
                "status": "failed",
            },
        )
        return

    if not upper_exists or not lower_exists:
        recognized["详情静态"]["模式"] = "上/下结构不完整"
        missing = [
            name for name, exists in (("上", upper_exists), ("下", lower_exists))
            if not exists
        ]
        _add_problem(
            problems,
            f"详情页上/下结构不完整：缺少目录 {', '.join(missing)}",
            static_root,
            "同时创建详情\\静态\\上和详情\\静态\\下，并在两个目录中分别放入图片",
        )
        logger.warning(
            "详情页结构检测失败：缺少上/下目录 missing=%r",
            missing,
            extra={
                "stage": "输入检测",
                "event": "详情结构检测",
                "status": "failed",
            },
        )
        return

    if not upper_images or not lower_images:
        recognized["详情静态"]["模式"] = "上/下结构不完整"
        empty = [
            name for name, images in (("上", upper_images), ("下", lower_images))
            if not images
        ]
        _add_problem(
            problems,
            f"详情页上/下目录必须分别包含图片：空目录 {', '.join(empty)}",
            static_root,
            "在详情\\静态\\上和详情\\静态\\下中分别放入图片",
        )
        logger.warning(
            "详情页结构检测失败：上/下目录为空 empty=%r",
            empty,
            extra={
                "stage": "输入检测",
                "event": "详情结构检测",
                "status": "failed",
            },
        )
        return

    recognized["详情静态"]["模式"] = "上/下"
    logger.info(
        "详情页结构检测通过 mode=upper-lower upper_count=%d lower_count=%d",
        len(upper_images),
        len(lower_images),
        extra={
            "stage": "输入检测",
            "event": "详情结构检测",
            "status": "success",
        },
    )


def _check_optional_material_directory(
    source_root: Path,
    warnings: list[dict[str, Any]],
    recognized: dict[str, dict[str, Any]],
) -> None:
    material_path = resolve_source_path(source_root, "素材图")
    if not material_path.is_dir():
        warnings.append({"信息": "未提供可选目录：素材图", "路径": str(material_path)})
        return
    images = list_images(material_path, recursive=True)
    recognized["素材图"] = {"目录": str(material_path), "图片数量": len(images)}
    if not images:
        warnings.append({"信息": "可选目录素材图为空", "路径": str(material_path)})


def _check_transparent_image(
    image_path: Path,
    problems: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
    visualization_dir: Path | None,
    allowed_subject_count: int | None = None,
) -> Path | None:
    """检查透明图中的主体组成部分和独立残留。

    功能说明：读取透明通道并分类所有独立区域；显著区域作为主体组成部分，
    极小区域作为脏点，中间区域要求通过文件规则确认。
    参数：
        image_path：待检查的透明图片路径。
        problems：用于追加阻断问题的列表。
        warnings：用于追加多主体提示的列表。
        visualization_dir：诊断图输出目录；为空时不生成诊断图。
        allowed_subject_count：文件规则允许的最大主体区域数。
    返回值：
        生成的诊断图路径；没有阻断问题或未生成诊断图时返回 None。
    """
    try:
        with Image.open(image_path) as image:
            image_format = (image.format or image_path.suffix.lstrip(".")).upper()
            rgba = image.convert("RGBA")
            alpha = rgba.getchannel("A")
    except Exception as exc:
        _add_problem(problems, "透明图无法读取", image_path, str(exc))
        return None

    if image_format != "PNG":
        _add_problem(problems, f"透明图必须为PNG，实际为{image_format}", image_path)
    minimum, maximum = alpha.getextrema()
    if minimum == maximum == 255:
        _add_problem(problems, "透明图没有实际透明背景", image_path)
        return None
    components = _alpha_components(alpha, 透明可见阈值)
    if not components:
        _add_problem(problems, "透明图没有可见主体", image_path)
        return None

    if allowed_subject_count is not None:
        subjects = components[:allowed_subject_count]
        debris = components[allowed_subject_count:]
        uncertain: list[dict[str, Any]] = []
        classification = "文件规则"
    else:
        subjects, debris, uncertain = _classify_transparent_components(components)
        classification = "自动判断"

    logger.info(
        "透明图独立区域分类完成 path=%r total=%d subjects=%d uncertain=%d debris=%d method=%s",
        str(image_path),
        len(components),
        len(subjects),
        len(uncertain),
        len(debris),
        classification,
        extra={
            "stage": "输入检测",
            "event": "透明图独立区域分类",
            "status": "success" if not debris and not uncertain else "failed",
        },
    )
    if len(subjects) > 1:
        warnings.append({
            "信息": "透明图包含多个主体组成部分",
            "路径": str(image_path),
            "主体区域数": len(subjects),
            "主体边界": [item["边界"] for item in subjects],
            "判定方式": classification,
        })

    issue_regions = [*debris, *uncertain]
    diagnostic_path = None
    if issue_regions and visualization_dir is not None:
        diagnostic_path = render_transparent_issue(
            image_path,
            rgba,
            alpha,
            issue_regions,
            visualization_dir,
            alpha_threshold=透明可见阈值,
        )

    if debris:
        if allowed_subject_count is not None:
            message = "透明图独立区域数超过配置允许主体数"
            suggestion = (
                f"请清理多余区域，或确认后调整{透明图规则文件名}中的允许主体数"
            )
        else:
            message = "透明图主体外存在独立残留像素"
            suggestion = "请清理主体外脏点后重新处理"
        extra = {
            "主体外独立区域数": len(debris),
            "主体外像素数": sum(item["像素数"] for item in debris),
            "最大残留透明度": max(item["最大透明度"] for item in debris),
            "残留边界": [item["边界"] for item in debris[:20]],
        }
        if allowed_subject_count is not None:
            extra["允许主体数"] = allowed_subject_count
        if diagnostic_path:
            extra["可视化诊断图"] = str(diagnostic_path)
        _add_problem(
            problems,
            message,
            image_path,
            suggestion,
            **extra,
        )
    if uncertain:
        _add_problem(
            problems,
            "透明图存在无法自动判断的独立区域",
            image_path,
            f"确认属于商品后，在{透明图规则文件名}中为该图片设置允许主体数",
            待确认区域数=len(uncertain),
            待确认区域=[_component_report(item) for item in uncertain],
            **({"可视化诊断图": str(diagnostic_path)} if diagnostic_path else {}),
        )
    return diagnostic_path


def _load_transparent_component_rules(
    transparent_root: Path,
    problems: list[dict[str, Any]],
) -> dict[str, int]:
    """读取透明图文件级主体数量规则。

    功能说明：读取透明图目录中的可选 JSON 配置，校验每张图片允许的最大
    主体区域数，并返回以相对路径为键的规则。
    参数：
        transparent_root：透明图目录。
        problems：用于追加配置问题的列表。
    返回值：
        图片相对路径到允许主体数的映射。
    """
    config_path = transparent_root / 透明图规则文件名
    if not config_path.exists():
        return {}
    if not config_path.is_file():
        _add_problem(problems, "透明图规则必须是JSON文件", config_path)
        return {}
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _add_problem(problems, "透明图规则无法读取", config_path, str(exc))
        return {}
    file_rules = data.get("文件规则") if isinstance(data, dict) else None
    if not isinstance(file_rules, dict):
        _add_problem(
            problems,
            "透明图规则缺少有效的文件规则",
            config_path,
            '使用格式：{"文件规则":{"颜色.png":{"允许主体数":2}}}',
        )
        return {}

    rules: dict[str, int] = {}
    for raw_name, raw_rule in file_rules.items():
        candidate = str(raw_name).replace("\\", "/").strip()
        while candidate.startswith("./"):
            candidate = candidate[2:]
        relative_path = PurePosixPath(candidate)
        normalized = relative_path.as_posix()
        allowed = raw_rule.get("允许主体数") if isinstance(raw_rule, dict) else None
        if (
            not normalized
            or relative_path.is_absolute()
            or ".." in relative_path.parts
            or isinstance(allowed, bool)
            or not isinstance(allowed, int)
            or allowed < 1
        ):
            _add_problem(
                problems,
                "透明图文件规则无效",
                config_path,
                "图片路径使用透明图目录内的相对路径，允许主体数必须为正整数",
                图片=str(raw_name),
            )
            continue
        rules[normalized] = allowed
    logger.info("透明图主体数量规则加载完成 path=%r count=%d", str(config_path), len(rules))
    return rules


def _classify_transparent_components(
    components: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """将透明图独立区域分类为主体、脏点和待确认区域。

    功能说明：以最大区域为主主体，结合面积比例和边界长边比例判断其他
    区域；明显区域作为主体组成部分，极小区域作为脏点，其余区域待确认。
    参数：
        components：按像素数从大到小排序的透明区域。
    返回值：
        主体区域、脏点区域和待确认区域三个列表。
    """
    main = components[0]
    main_pixels = max(1, main["像素数"])
    main_long_edge = max(1, _component_long_edge(main))
    subjects = [main]
    debris = []
    uncertain = []
    for component in components[1:]:
        area_ratio = component["像素数"] / main_pixels
        long_edge_ratio = _component_long_edge(component) / main_long_edge
        component["面积占主主体比例"] = round(area_ratio, 6)
        component["长边占主主体比例"] = round(long_edge_ratio, 6)
        is_subject = (
            area_ratio >= 明确主体最小面积比例
            or (
                area_ratio >= 细长主体最小面积比例
                and long_edge_ratio >= 明确主体最小长边比例
            )
        )
        is_debris = (
            component["像素数"] <= 明确脏点最大像素数
            or (
                area_ratio <= 明确脏点最大面积比例
                and long_edge_ratio <= 明确脏点最大长边比例
            )
        )
        if is_subject:
            subjects.append(component)
        elif is_debris:
            debris.append(component)
        else:
            uncertain.append(component)
    return subjects, debris, uncertain


def _component_long_edge(component: dict[str, Any]) -> int:
    """返回连通区域边界框的长边像素数。"""
    left, top, right, bottom = component["边界"]
    return max(right - left, bottom - top)


def _component_report(component: dict[str, Any]) -> dict[str, Any]:
    """返回适合写入报告的连通区域摘要。"""
    return {
        key: value
        for key, value in component.items()
        if key != "起点"
    }


def _alpha_components(
    alpha: Image.Image,
    threshold: int = 透明可见阈值,
) -> list[dict[str, Any]]:
    """提取透明通道中所有八邻域可见连通区域。

    参数：
        alpha：待分析的透明通道。
        threshold：视为可见像素的最小透明度，不超过该值时按透明处理。
    返回值：
        按像素数从大到小排序的独立区域信息。
    """
    width, height = alpha.size
    values = alpha.tobytes()
    seen = bytearray(width * height)
    components = []
    for start, value in enumerate(values):
        if value <= threshold or seen[start]:
            continue
        seen[start] = 1
        queue = deque([start])
        count = 0
        min_x = max_x = start % width
        min_y = max_y = start // width
        max_alpha = 0
        while queue:
            current = queue.popleft()
            x = current % width
            y = current // width
            count += 1
            min_x, max_x = min(min_x, x), max(max_x, x)
            min_y, max_y = min(min_y, y), max(max_y, y)
            max_alpha = max(max_alpha, values[current])
            for neighbor_y in range(max(0, y - 1), min(height, y + 2)):
                base = neighbor_y * width
                for neighbor_x in range(max(0, x - 1), min(width, x + 2)):
                    neighbor = base + neighbor_x
                    if values[neighbor] > threshold and not seen[neighbor]:
                        seen[neighbor] = 1
                        queue.append(neighbor)
        components.append({
            "像素数": count,
            "边界": [min_x, min_y, max_x + 1, max_y + 1],
            "最大透明度": max_alpha,
            "起点": [start % width, start // width],
        })
    return sorted(components, key=lambda item: item["像素数"], reverse=True)


def _add_problem(
    problems: list[dict[str, Any]],
    message: str,
    path: Path,
    suggestion: str = "",
    **extra: Any,
) -> None:
    item = {"信息": message, "路径": str(path)}
    if suggestion:
        item["处理建议"] = suggestion
    item.update(extra)
    problems.append(item)


def _display_path(source_root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(source_root))
    except ValueError:
        return str(path)


def _result(
    problems: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
    recognized: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    result = {
        "通过": not problems,
        "问题": problems,
        "警告": warnings,
        "识别目录": recognized,
    }
    if problems:
        result["标准输入结构"] = 标准输入结构
    return result
