from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from common.font_assets import load_font_assets
from common.material_editor import (
    TextStyle,
    measure_material_layout,
    replace_material_text,
    verify_measured_material_layout,
    verify_non_target_unchanged,
)
from common.utils import add_report_item

from .business_support import (
    load_plan,
    parse_box,
    resolve_relative_image,
)

logger = logging.getLogger(__name__)


def apply_material_plan(
    source_root: Path,
    expected: str,
    plan_path: Path | None,
    staging_root: Path,
    report: dict[str, Any],
) -> dict[Path, Path] | None:
    """按视觉定位计划生成需要修正的详情图。

    功能说明：只读检查源详情图，使用 Excel 中文原文右对齐重绘全部
    已定位面料区域，并返回原图到修正版的路径映射供平台详情页使用。
    参数：
        source_root：只读的产品目录或数据包目录。
        expected：Excel 中文面料原文。
        plan_path：Agent 生成的视觉定位计划。
        staging_root：仅存放面料修正版的任务临时目录。
        report：完整处理报告。
    返回值：
        成功时返回原图到修正版的映射；失败时返回 None。
    """
    if plan_path is None:
        add_report_item(report, "失败项", "缺少面料视觉定位计划，无法确认全部详情页面料区域")
        report["Agent复核建议"].append(
            {
                "任务名称": "定位详情页面料区域",
                "图片路径": [str(source_root)],
                "原因": "需要提供每处文字的相对图片路径、识别原文、区域和上下字段参考区域",
            }
        )
        return None
    plan = load_plan(plan_path)
    items = plan.get("面料区域")
    if not isinstance(items, list) or not items:
        add_report_item(report, "失败项", "面料视觉定位计划没有“面料区域”列表")
        return None
    fonts = load_font_assets()
    source_root = source_root.resolve()
    staging_root.mkdir(parents=True, exist_ok=True)
    replacements: dict[Path, Path] = {}
    passed = True
    logger.info("开始检查详情页面料 source=%r items=%d", str(source_root), len(items))
    for index, raw in enumerate(items, start=1):
        if not isinstance(raw, dict):
            add_report_item(report, "失败项", "面料计划项格式无效", 序号=index)
            passed = False
            continue
        try:
            image = resolve_relative_image(source_root, str(raw["图片"])).resolve()
            actual = str(raw["识别原文"])
            region = parse_box(raw["区域"], "面料区域")
            reference_values = raw.get("右侧字段参考区域")
            if not isinstance(reference_values, list) or not reference_values:
                raise RuntimeError("面料计划缺少右侧字段参考区域")
            reference_regions = [
                parse_box(value, "右侧字段参考区域") for value in reference_values
            ]
            result: dict[str, Any] = {
                "图片": str(image),
                "Excel原文": expected,
                "识别原文": actual,
                "区域": list(region),
            }
            if not image.is_file():
                raise RuntimeError(f"详情图不存在：{image}")
            color = tuple(int(value) for value in raw.get("颜色", [0, 0, 0]))
            background = tuple(int(value) for value in raw["背景色"])
            padding = tuple(int(value) for value in raw.get("内边距", [0, 0]))
            current_source = replacements.get(image, image)
            layout = measure_material_layout(
                current_source,
                region,
                reference_regions,
                expected,
                fonts,
                background,
                padding[0],
            )
            style = TextStyle(
                layout.font_size,
                color,
                layout.line_spacing,
            )
            result["测量字号"] = layout.font_size
            result["测量右边界"] = layout.reference_right
            result["原文字高"] = layout.source_ink_height
            result["右侧字段参考区域"] = [list(value) for value in reference_regions]
            relative = image.relative_to(source_root)
            corrected = staging_root / relative.parent / f"{relative.name}.png"
            corrected.parent.mkdir(parents=True, exist_ok=True)
            temporary = corrected.with_name(f".{corrected.stem}-material-temp{corrected.suffix}")
            replace_material_text(
                current_source,
                temporary,
                region,
                expected,
                fonts,
                style,
                background,
                (padding[0], layout.padding_top),
                layout.text_right,
            )
            verify_measured_material_layout(
                temporary,
                region,
                background,
                layout.reference_right,
                layout.source_ink_height,
            )
            if not verify_non_target_unchanged(
                current_source,
                temporary,
                [region],
                difference_threshold=12,
                maximum_changed_ratio=0.002,
            ):
                temporary.unlink(missing_ok=True)
                raise RuntimeError("非目标区域变化超过允许边界")
            temporary.replace(corrected)
            replacements[image] = corrected
            result["已修改"] = True
            result["输出用途"] = "平台详情页"
            report["面料检查"]["检查项"].append(result)
            logger.info("面料计划项处理完成 image=%r changed=%s", str(image), result["已修改"])
        except Exception as exc:
            add_report_item(report, "失败项", "面料计划项处理失败", 序号=index, 错误=str(exc))
            passed = False
    logger.info(
        "详情页面料检查结束 passed=%s corrected_images=%d",
        passed,
        len(replacements),
    )
    return replacements if passed else None
