from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .scan_source_pack import resolve_sku_root, resolve_source_path
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


def validate_source_pack(source_root: Path) -> dict[str, Any]:
    """强制检查标准输入文件夹结构。

    功能说明：检查标准目录名称、必需目录是否存在且包含图片，
    并验证详情页目录结构。

    参数：
        source_root：待处理的数据包根目录。
    返回值：
        包含“通过”“问题”“警告”和“识别目录”的结构化检测结果。
    """
    problems: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    recognized: dict[str, dict[str, Any]] = {}
    logger.info("开始强制检测输入包结构：%s", source_root)

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

    result = _result(problems, warnings, recognized)
    if result["通过"]:
        logger.info("输入包结构检测通过：%s", source_root)
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
