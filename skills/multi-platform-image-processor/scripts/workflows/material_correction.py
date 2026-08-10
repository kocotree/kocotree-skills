from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from common.font_assets import load_font_assets
from common.material_editor import (
    TextStyle,
    compare_material,
    replace_material_text,
    verify_non_target_unchanged,
)
from common.workflow_report import add_report_item

from .business_support import (
    load_plan,
    parse_box,
    resolve_relative_image,
)

logger = logging.getLogger(__name__)


def apply_material_plan(
    working_root: Path,
    expected: str,
    plan_path: Path | None,
    report: dict[str, Any],
) -> bool:
    """按视觉定位计划检查并修正全部面料区域。

    参数：
        working_root：允许修改的本地工作副本。
        expected：Excel 中文面料原文。
        plan_path：Agent 生成的视觉定位计划。
        report：业务顶层报告。
    返回值：
        全部计划项检查或修正成功时返回 True。
    """
    if plan_path is None:
        add_report_item(report, "失败项", "缺少面料视觉定位计划，无法确认全部详情页面料区域")
        report["Agent复核建议"].append(
            {
                "任务名称": "定位详情页面料区域",
                "图片路径": [str(working_root)],
                "原因": "需要提供每处文字的相对图片路径、识别原文、区域和版式参数",
            }
        )
        return False
    plan = load_plan(plan_path)
    items = plan.get("面料区域")
    if not isinstance(items, list) or not items:
        add_report_item(report, "失败项", "面料视觉定位计划没有“面料区域”列表")
        return False
    fonts = load_font_assets()
    passed = True
    for index, raw in enumerate(items, start=1):
        if not isinstance(raw, dict):
            add_report_item(report, "失败项", "面料计划项格式无效", 序号=index)
            passed = False
            continue
        try:
            image = resolve_relative_image(working_root, str(raw["图片"]))
            actual = str(raw["识别原文"])
            region = parse_box(",".join(str(value) for value in raw["区域"]), "面料区域")
            check = compare_material(expected, actual)
            result: dict[str, Any] = {
                "图片": str(image),
                "Excel原文": expected,
                "识别原文": actual,
                "一致": check.matches,
                "区域": list(region),
            }
            if not image.is_file():
                raise RuntimeError(f"详情图不存在：{image}")
            if not check.matches:
                color = tuple(int(value) for value in raw.get("颜色", [0, 0, 0]))
                background = tuple(int(value) for value in raw["背景色"])
                padding = tuple(int(value) for value in raw.get("内边距", [0, 0]))
                style = TextStyle(
                    int(raw["字号"]),
                    color,
                    int(raw.get("行距", 6)),
                )
                temporary = image.with_name(f".{image.stem}-material-temp{image.suffix}")
                replace_material_text(image, temporary, region, expected, fonts, style, background, padding)
                if not verify_non_target_unchanged(
                    image,
                    temporary,
                    [region],
                    difference_threshold=12,
                    maximum_changed_ratio=0.002,
                ):
                    temporary.unlink(missing_ok=True)
                    raise RuntimeError("非目标区域变化超过允许边界")
                temporary.replace(image)
                result["已修改"] = True
            else:
                result["已修改"] = False
            report["面料检查"]["检查项"].append(result)
            logger.info("面料计划项处理完成 image=%r changed=%s", str(image), result["已修改"])
        except Exception as exc:
            add_report_item(report, "失败项", "面料计划项处理失败", 序号=index, 错误=str(exc))
            passed = False
    return passed
