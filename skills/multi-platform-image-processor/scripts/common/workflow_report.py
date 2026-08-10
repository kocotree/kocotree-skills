from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from .utils import ensure_dir


logger = logging.getLogger(__name__)


def new_workflow_report(mode: str, source: Path, output: Path) -> dict[str, Any]:
    """创建业务工作流顶层报告。

    参数：
        mode：运行模式。
        source：源目录。
        output：预期输出目录。
    返回值：
        可持续补充的报告对象。
    """
    return {
        "工作流": {
            "运行模式": mode,
            "开始时间": datetime.now().isoformat(timespec="seconds"),
            "结束时间": "",
            "完成状态": "进行中",
        },
        "产品匹配": {},
        "路径": {"源路径": str(source), "最终输出": str(output)},
        "面料检查": {"Excel中文原文": "", "检查项": []},
        "BarTender导出": {},
        "业务图片": {},
        "平台子报告": {},
        "Agent复核建议": [],
        "警告": [],
        "风险": [],
        "失败项": [],
        "汇总": {},
    }


def add_report_item(report: dict[str, Any], level: str, message: str, **extra: Any) -> None:
    """向顶层报告追加结构化问题项。"""
    item = {"信息": message, **extra}
    report[level].append(item)
    log = logger.error if level == "失败项" else logger.warning
    log("工作流问题 level=%s message=%s extra=%r", level, message, extra)


def merge_platform_report(report: dict[str, Any], platform_report: dict[str, Any], path: Path) -> None:
    """将平台子报告的结论合并到业务报告。

    参数：
        report：业务顶层报告。
        platform_report：六平台处理报告。
        path：平台报告文件路径。
    返回值：
        无返回值。
    """
    report["平台子报告"] = {
        "报告路径": str(path),
        "输出目录": platform_report.get("处理配置", {}).get("输出目录", ""),
        "汇总": platform_report.get("汇总", {}),
    }
    for level in ("警告", "风险", "失败项", "Agent复核建议"):
        for item in platform_report.get(level, []):
            copied = dict(item)
            copied.setdefault("来源", "平台处理")
            report[level].append(copied)


def finalize_workflow_report(report: dict[str, Any]) -> None:
    """计算业务报告完成状态和汇总。"""
    report["工作流"]["结束时间"] = datetime.now().isoformat(timespec="seconds")
    if report["失败项"]:
        status = "失败"
    elif report["Agent复核建议"]:
        status = "部分完成"
    else:
        status = "完成"
    report["工作流"]["完成状态"] = status
    report["汇总"] = {
        "业务图片数": sum(
            1 for item in report.get("业务图片", {}).values()
            if isinstance(item, dict) and item.get("状态") == "成功"
        ),
        "面料检查数": len(report.get("面料检查", {}).get("检查项", [])),
        "Agent复核建议数": len(report["Agent复核建议"]),
        "警告数": len(report["警告"]),
        "风险数": len(report["风险"]),
        "失败数": len(report["失败项"]),
    }


def write_workflow_report(report: dict[str, Any], path: Path) -> Path:
    """完成并写出 UTF-8 业务报告。

    参数：
        report：业务报告对象。
        path：目标 JSON 文件。
    返回值：
        报告文件路径。
    """
    finalize_workflow_report(report)
    ensure_dir(path.parent)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("业务报告写入完成 path=%r status=%s", str(path), report["工作流"]["完成状态"])
    return path
