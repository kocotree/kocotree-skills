from __future__ import annotations

import logging
from collections import deque
from pathlib import Path
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
      └─ ..."""


def validate_source_pack(
    source_root: Path,
    visualization_dir: Path | None = None,
) -> dict[str, Any]:
    """强制检查标准输入文件夹结构和透明图脏点。

    功能说明：检查标准目录名称、必需目录是否存在且包含图片，并检查每张
    透明 PNG 是否具有透明通道以及主体之外的独立残留像素。

    参数：
        source_root：待处理的数据包根目录。
        visualization_dir：透明图脏点诊断图输出目录；未提供时只返回坐标数据。
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
    for image_path in list_images(transparent_path):
        diagnostic_path = _check_transparent_image(image_path, problems, visualization_dir)
        if diagnostic_path:
            diagnostic_paths.append(diagnostic_path)

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
    static_root = resolve_source_path(source_root, "详情静态")
    if not static_root.is_dir():
        _add_problem(problems, "缺少必需目录：详情\\静态", static_root)
        return

    direct_images = list_images(static_root)
    upper_images = list_images(resolve_source_path(source_root, "详情上"))
    lower_images = list_images(resolve_source_path(source_root, "详情下"))
    recognized["详情静态"] = {
        "目录": str(static_root),
        "直接图片数量": len(direct_images),
        "上部图片数量": len(upper_images),
        "下部图片数量": len(lower_images),
    }
    if direct_images or (upper_images and lower_images):
        return
    _add_problem(
        problems,
        "详情页结构无效：请在详情\\静态直接放图片，或同时提供详情\\静态\\上和详情\\静态\\下",
        static_root,
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
    visualization_dir: Path | None,
) -> Path | None:
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
    components = _alpha_components(alpha)
    if not components:
        _add_problem(problems, "透明图没有可见主体", image_path)
        return None
    debris = components[1:]
    if debris:
        diagnostic_path = None
        if visualization_dir is not None:
            diagnostic_path = render_transparent_issue(
                image_path,
                rgba,
                alpha,
                debris,
                visualization_dir,
            )
        _add_problem(
            problems,
            "透明图主体外存在独立残留像素",
            image_path,
            "请清理主体外脏点后重新处理",
            主体外独立区域数=len(debris),
            主体外像素数=sum(item["像素数"] for item in debris),
            最大残留透明度=max(item["最大透明度"] for item in debris),
            残留边界=[item["边界"] for item in debris[:20]],
            **({"可视化诊断图": str(diagnostic_path)} if diagnostic_path else {}),
        )
        return diagnostic_path
    return None


def _alpha_components(alpha: Image.Image) -> list[dict[str, Any]]:
    """提取透明通道中所有八邻域可见连通区域。"""
    width, height = alpha.size
    values = alpha.tobytes()
    seen = bytearray(width * height)
    components = []
    for start, value in enumerate(values):
        if value == 0 or seen[start]:
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
                    if values[neighbor] > 0 and not seen[neighbor]:
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
