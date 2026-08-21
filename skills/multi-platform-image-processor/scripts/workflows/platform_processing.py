from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from common import (
    add_failure,
    add_platform_result,
    build_platform_directory_names,
    copy_template_empty_dirs,
    ensure_dir,
    全部平台,
    平台模板目录名,
)
from common.quality_audit import audit_sku_branch_outputs, run_quality_audit
from common.color_naming import resolve_color_names
from platforms.cbme import derive as derive_cbme
from platforms.fengxiang_aikucun import derive as derive_fengxiang_aikucun
from platforms.jd import derive as derive_jd
from platforms.offsite import derive as derive_offsite
from platforms.tmall import build as build_tmall
from platforms.vip import derive as derive_vip

logger = logging.getLogger(__name__)


def default_template_path() -> Path:
    """返回 Skill 内置平台模板目录。"""
    return Path(__file__).resolve().parents[2] / "template"


def default_output_path() -> Path:
    """返回跨平台兼容的默认输出目录。"""
    desktop = Path("E:/桌面")
    if not desktop.exists():
        desktop = Path.home() / "Desktop"
    return desktop / "multi-platform-image-processor" / "output"


def resolve_source_and_output(
    source: Path,
    output_root: Path,
    timestamp: str | None = None,
) -> tuple[Path, Path, str]:
    """解析产品素材根目录和带产品名的时间戳输出目录。

    参数：
        source：数据包目录或产品目录。
        output_root：本次处理的输出根目录。
        timestamp：可选的固定交付时间戳。
    返回值：
        实际素材目录、产品输出目录和源产品目录名。
    """
    output_timestamp = timestamp or datetime.now().strftime("%Y%m%d-%H%M%S")
    if source.name == "数据包":
        product_name = source.parent.name
        return source, output_root / f"{product_name}_{output_timestamp}", product_name
    data_pack = source / "数据包"
    if data_pack.is_dir():
        return data_pack, output_root / f"{source.name}_{output_timestamp}", source.name
    product_name = source.name
    return source, output_root / f"{product_name}_{output_timestamp}", product_name


def run_platform_processing(
    source_arg: Path,
    template: Path,
    output_arg: Path,
    report: dict,
    product_code: str = "",
    product_name: str = "",
    detail_plan: Path | None = None,
    detail_overrides: dict[Path, Path] | None = None,
    color_name_plan: object | None = None,
    delivery_timestamp: str | None = None,
) -> tuple[int, Path]:
    """处理单个产品并生成六平台图片。

    参数：
        source_arg：数据包目录或产品目录。
        template：平台模板路径。
        output_arg：输出根目录。
        report：完整产品处理报告。
        product_code：Excel 确认的产品货号，用于构造京东目录名。
        product_name：Excel 确认的产品名称，用于构造京东目录名。
        detail_plan：Agent 视觉检查生成的详情模块计划路径。
        detail_overrides：原始详情图到临时面料修正版的映射。
        color_name_plan：白底图、透明图相对路径到 SKU 颜色名称的视觉映射。
        delivery_timestamp：内部暂存与最终交付共用的时间戳。
    返回值：
        退出码和实际输出目录。
    """
    source, output, source_product_name = resolve_source_and_output(
        source_arg,
        output_arg,
        delivery_timestamp,
    )
    effective_product_name = product_name.strip() or source_product_name
    report["处理配置"].update(
        {"源目录": str(source), "模板目录": str(template), "输出目录": str(output)}
    )
    if effective_product_name:
        report["处理配置"]["产品名"] = effective_product_name
        report["处理配置"]["源参数目录"] = str(source_arg)
        report["处理配置"]["输出根目录"] = str(output_arg)
    if product_name.strip():
        logger.info(
            "平台目录使用已确认产品身份 code=%s name=%s",
            product_code,
            effective_product_name,
        )
    else:
        logger.warning(
            "未提供确认产品名称，平台目录使用源目录名称 name=%s",
            effective_product_name,
        )
    logger.info("六平台任务开始 source=%r output=%r", str(source), str(output))
    if not source.exists():
        add_failure(report, "源数据包目录不存在", 源目录=str(source))
        return 2, output

    ensure_dir(output)
    color_names = resolve_color_names(source, color_name_plan)
    directory_names = build_platform_directory_names(product_code, effective_product_name)
    platform_directories = {
        key: output / directory_names[key]
        for key in 全部平台
    }
    for key in 全部平台:
        copy_template_empty_dirs(template, 平台模板目录名[key], platform_directories[key])

    tmall_dir = build_tmall(source, output, report, detail_plan, detail_overrides, color_names)
    derive_cbme(source, tmall_dir, output, report)
    derive_jd(source, tmall_dir, platform_directories["jd"], report, color_names)
    derive_vip(source, tmall_dir, output, report, color_names)
    derive_fengxiang_aikucun(source, tmall_dir, output, report, color_names)
    derive_offsite(source, template, output, report, color_names)

    run_quality_audit(report, platform_directories)
    audit_sku_branch_outputs(source, platform_directories, report)
    for key in 全部平台:
        add_platform_result(report, directory_names[key], platform_directories[key])
    exit_code = 0 if not report["失败项"] else 1
    logger.info("平台任务结束 output=%r code=%d", str(output), exit_code)
    return exit_code, output
