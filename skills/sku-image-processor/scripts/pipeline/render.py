"""render 阶段：按标注清单逐商品逐颜色合成 SKU 图，验收后输出交付件与报告。

输出固定为三类图片：
- final/: 验收 pass 的最终交付图。
- work/annotated/: 网格、骨架、源图裁切框、生图补齐和成品拼接示例等标注图片。
- work/crops/: 按最终 crop_box 裁出的检查图。
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from PIL import Image

from core.annotations import annotation_is_valid, load_annotations, resolve_product_dir
from core.config import WorkflowConfig, load_config
from core.geometry import empty_layout
from core.output_layout import OutputLayout, layout_from_annotations, update_summary
from core.utils import clear_directory, get_logger
from model.place import FillModelRetryableError, place_from_annotation
from product.product_render import draw_label, place_product
from qa.preview import build_contact_sheet, save_preview
from qa.validation import validate_layout
from template.template import get_clean_template, get_template_regions

logger = get_logger(__name__)

FILL_MODEL_RETRY_DELAY_SECONDS = 8


def run_render(
    input_root: Path,
    output_root: Path,
    qa_root: Path,
    font_path: Path,
    annotations_path: Path,
    template_path: Path | None = None,
    clean_output: bool = True,
) -> dict[str, Any]:
    """按标注清单合成所有 SKU 图并输出交付件与报告。

    参数:
        input_root: 素材根目录（用于定位透明商品图）。
        output_root: 成品交付目录，固定为批次 final/。
        qa_root: 批次输出目录；兼容参数，实际布局由 annotations_path 解析。
        font_path: 颜色名标签字体路径。
        annotations_path: prep 生成、agent 填好的标注清单路径。
        template_path: 模板路径；若 input_root 下存在 模板.png 则优先使用它。
        clean_output: 是否在开始前清空 output_root（默认清空）。
    返回:
        完整报告字典（含每个商品、每个颜色的状态与汇总）。
    """
    if not input_root.exists():
        raise FileNotFoundError(f"素材根目录不存在: {input_root}")
    if not annotations_path.exists():
        raise FileNotFoundError(f"未找到标注清单: {annotations_path}，请先运行 prep")

    # 模板优先级：input_root/模板.png > 传入的 template_path
    input_template = input_root / "模板.png"
    if input_template.exists():
        template_path = input_template
    if template_path is None or not template_path.exists():
        raise FileNotFoundError(f"未找到模板: {template_path or input_template}")
    if not font_path.exists():
        raise FileNotFoundError(f"未找到指定字体: {font_path}")

    cfg = load_config(template_path)
    # clean_template / 参考线图与具体商品无关，按模板缓存复用，仅模板或配置变化时重建
    clean_template, sampled_green = get_clean_template(template_path, cfg)
    if clean_template.width != clean_template.height:
        logger.warning("模板非正方形 (%dx%d)，按宽度作为画布边长", clean_template.width, clean_template.height)
    cfg.canvas_size = clean_template.width  # 画布尺寸跟随模板尺寸
    template_regions = get_template_regions(template_path, clean_template, cfg)
    annotations = load_annotations(annotations_path)
    logger.info("开始 render：模板=%s 画布=%d 清单=%s", template_path, cfg.canvas_size, annotations_path)

    if clean_output and output_root.exists():
        clear_directory(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    layout = layout_from_annotations(annotations_path)
    if layout.batch_root.resolve() != qa_root.resolve():
        logger.warning("传入批次目录与 annotations 路径不一致，使用后者: %s", layout.batch_root)
    if output_root.resolve() != layout.final_dir.resolve():
        logger.warning("传入成品目录与固定 final 目录不一致，使用后者: %s", layout.final_dir)
        output_root = layout.final_dir
    layout.work_dir.mkdir(parents=True, exist_ok=True)
    layout.annotated_dir.mkdir(parents=True, exist_ok=True)
    clear_directory(layout.crops_dir)
    for old_preview in layout.annotated_dir.rglob("*_preview_boxes.jpg"):
        old_preview.unlink()
    for old_crop_box in layout.annotated_dir.rglob("*_crop_box.jpg"):
        old_crop_box.unlink()
    layout.template_regions_path.parent.mkdir(parents=True, exist_ok=True)
    template_regions.save(layout.template_regions_path, quality=95)

    report: dict[str, Any] = {
        "version": "apparel_layered_v3",
        "input_root": str(input_root),
        "output_root": str(layout.batch_root),
        "work_root": str(layout.work_dir),
        "final_root": str(output_root),
        "annotated_root": str(layout.annotated_dir),
        "crops_root": str(layout.crops_dir),
        "font": str(font_path),
        "template": {
            "path": str(template_path),
            "canvas_size": cfg.canvas_size,
            "sampled_green": sampled_green,
            "layout": {key: list(value) for key, value in vars(cfg.layout).items()},
        },
        "items": [],
    }

    products = annotations.get("products", {})
    logger.info("清单含 %d 个商品", len(products))
    retry_queue: list[dict[str, Any]] = []
    for product_name, colors in products.items():
        report["items"].append(
            _process_product(
                product_name,
                colors,
                input_root,
                output_root,
                layout,
                clean_template,
                cfg,
                font_path,
                retry_queue,
            )
        )

    _retry_fill_model_items(retry_queue, report)
    build_contact_sheet(output_root, layout.contact_sheet_path)
    if layout.contact_sheet_path.exists():
        report["contact_sheet"] = str(layout.contact_sheet_path)
    report["summary"] = _summarize_report(report)
    update_summary(layout, "render", report)
    logger.info("render 结束：%s", report["summary"])
    return report


def _process_product(
    product_name: str,
    colors: dict[str, Any],
    input_root: Path,
    output_root: Path,
    layout: OutputLayout,
    clean_template: Image.Image,
    cfg: WorkflowConfig,
    font_path: Path,
    retry_queue: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """处理单个商品：逐颜色合成并汇总状态。

    参数:
        product_name: 商品名。
        colors: 该商品下 {颜色: 清单条目} 字典。
        input_root: 素材根目录（定位透明商品图）。
        output_root: 成品交付目录。
        layout: 输出路径布局。
        clean_template: 干净模板图层。
        cfg: 工作流配置。
        font_path: 标签字体路径。
        retry_queue: 生图补齐失败的批次末尾重试队列，可为空。
    返回:
        该商品的处理报告（status 取所有颜色中最差的）。
    """
    product_report: dict[str, Any] = {"product": product_name, "status": "pass", "items": []}
    out_product_dir = output_root / product_name
    product_dir = resolve_product_dir(input_root, product_name)
    transparent_dir = product_dir / "透明图"

    for color in sorted(colors):
        info = colors[color]
        transparent_path = transparent_dir / f"{color}.png"
        item = _process_color(
            color,
            info,
            transparent_path if transparent_path.exists() else None,
            out_product_dir,
            layout,
            product_name,
            clean_template,
            cfg,
            font_path,
        )
        product_report["items"].append(item)
        if retry_queue is not None and item.get("retryable_fill_model"):
            retry_queue.append(
                {
                    "product_report": product_report,
                    "item_index": len(product_report["items"]) - 1,
                    "process_args": (
                        color,
                        info,
                        transparent_path if transparent_path.exists() else None,
                        out_product_dir,
                        layout,
                        product_name,
                        clean_template,
                        cfg,
                        font_path,
                    ),
                }
            )
        if item["status"] == "fail":
            product_report["status"] = "fail"

    return product_report


def _process_color(
    color: str,
    info: dict[str, Any],
    transparent_path: Path | None,
    out_product_dir: Path,
    layout_paths: OutputLayout,
    product_name: str,
    clean_template: Image.Image,
    cfg: WorkflowConfig,
    font_path: Path,
) -> dict[str, Any]:
    """合成单个颜色的 SKU 图：放模特/商品/标签 → 验收 → 按结果输出 final。

    参数:
        color: 颜色名。
        info: 清单条目（含 bg_class、source_image、annotation）。
        transparent_path: 该颜色透明商品图路径，可为 None。
        out_product_dir: 该商品成品输出目录。
        layout_paths: 输出路径布局。
        product_name: 商品名。
        clean_template: 干净模板图层。
        cfg: 工作流配置。
        font_path: 标签字体路径。
    返回:
        该颜色的处理结果（status: pass/fail）。
    """
    bg_class = info.get("bg_class")
    source_image = info.get("source_image") or ""
    item: dict[str, Any] = {
        "color": color,
        "bg_class": bg_class,
        "model_path": source_image,
        "transparent_path": str(transparent_path) if transparent_path else "",
        "status": "fail",
        "failures": [],
    }
    try:
        has_model = bg_class in {"opaque", "transparent"} and source_image

        if has_model:
            # 模特图统一按 agent 标注裁切；背景来源由 bg_class 决定（自带/场景图）
            annotation = info.get("annotation")
            if not annotation_is_valid(annotation):
                item["failures"].append("缺少视觉标注：请在 annotations.json 中填写该颜色的 crop_box")
                logger.warning("颜色 %s 缺少有效标注，判 fail", color)
                return item
            crop_path = layout_paths.crop_path(product_name, color)
            skeleton_path = layout_paths.skeleton_path(product_name, color)
            fill_input_path = layout_paths.fill_input_path(product_name, color)
            fill_result_path = layout_paths.fill_result_path(product_name, color)
            for stale_path in [fill_input_path, fill_result_path]:
                if stale_path.exists():
                    stale_path.unlink()
            canvas, layout = place_from_annotation(
                Path(source_image),
                bg_class,
                annotation,
                cfg,
                qa_dir=layout_paths.batch_root,
                crop_output_path=crop_path,
                skeleton_path=skeleton_path,
                fill_input_path=fill_input_path,
                fill_result_path=fill_result_path,
            )
            item["crop"] = str(crop_path)
            item["skeleton"] = str(skeleton_path)
            if layout.get("fill_input"):
                item["fill_input"] = layout["fill_input"]
            if layout.get("fill_result"):
                item["fill_result"] = layout["fill_result"]

            if transparent_path:
                sticker = clean_template.copy()
                product_meta = place_product(sticker, transparent_path, cfg)
                label_meta = draw_label(sticker, color, cfg, font_path)
                canvas.alpha_composite(sticker)
                output_kind, extension = "complete_sku_jpg", ".jpg"
            else:
                product_meta, label_meta = {}, {}
                output_kind, extension = "model_only_jpg", ".jpg"
        elif transparent_path:
            # 只有透明商品图、没有模特图
            canvas = Image.new("RGBA", (cfg.canvas_size, cfg.canvas_size), (255, 255, 255, 255))
            canvas.alpha_composite(clean_template)
            layout = empty_layout("transparent_only")
            product_meta = place_product(canvas, transparent_path, cfg)
            label_meta = draw_label(canvas, color, cfg, font_path)
            output_kind, extension = "transparent_template_png", ".png"
        else:
            item["failures"].append("既无模特图也无透明商品图")
            logger.warning("颜色 %s 无任何素材", color)
            return item

        layout["product_image"] = product_meta
        layout["label"] = label_meta
        layout["output_kind"] = output_kind
        item["layout"] = layout

        validation = validate_layout(layout, cfg, output_kind)
        item["failures"].extend(validation["failures"])
        if item["failures"]:
            item["status"] = "fail"
        else:
            item["status"] = "pass"

        if item["status"] == "pass":
            out_product_dir.mkdir(parents=True, exist_ok=True)
            final_path = layout_paths.final_path(product_name, color, extension)
            save_preview(canvas, final_path, extension)
            item["final"] = str(final_path)
        logger.info("颜色 %s 处理完成：%s", color, item["status"])
        return item
    except FillModelRetryableError as exc:
        item["failures"].append(str(exc))
        item["retryable_fill_model"] = True
        logger.warning("颜色 %s 生图补齐失败，先跳过并加入批次末尾重试队列: %s", color, exc)
        return item
    except Exception as exc:  # 单色失败不影响其它颜色
        item["failures"].append(str(exc))
        logger.exception("颜色 %s 处理异常", color)
        return item


def _retry_fill_model_items(retry_queue: list[dict[str, Any]], report: dict[str, Any]) -> None:
    """批次末尾重试一次生图补齐失败的颜色。

    参数:
        retry_queue: 首次因生图补齐失败而跳过的颜色队列。
        report: render 汇总报告，函数会原地替换重试后的 item。
    返回:
        无返回值，直接更新 report。
    """
    if not retry_queue:
        report["fill_model_retry"] = {"queued": 0, "retried": 0, "recovered": 0, "failed": 0}
        return

    logger.warning("检测到 %d 个生图补齐失败项，等待 %d 秒后批次末尾重试一次",
                   len(retry_queue), FILL_MODEL_RETRY_DELAY_SECONDS)
    time.sleep(FILL_MODEL_RETRY_DELAY_SECONDS)
    recovered = 0
    still_failed = 0

    for task in retry_queue:
        product_report = task["product_report"]
        item_index = task["item_index"]
        color = task["process_args"][0]
        retry_item = _process_color(*task["process_args"])
        retry_item["fill_model_retry_attempts"] = 1
        if retry_item.get("status") == "pass":
            retry_item.pop("retryable_fill_model", None)
            retry_item["fill_model_retry_result"] = "recovered"
            recovered += 1
            logger.info("颜色 %s 生图补齐重试成功", color)
        else:
            retry_item["fill_model_retry_result"] = "failed"
            if retry_item.get("retryable_fill_model"):
                retry_item["failures"].append("生图 API 批次末尾重试 1 次后仍失败，请稍后重跑 render 或检查认证/服务状态")
            still_failed += 1
            logger.warning("颜色 %s 生图补齐重试后仍失败", color)
        product_report["items"][item_index] = retry_item
        _refresh_product_status(product_report)

    report["fill_model_retry"] = {
        "queued": len(retry_queue),
        "retried": len(retry_queue),
        "recovered": recovered,
        "failed": still_failed,
    }


def _refresh_product_status(product_report: dict[str, Any]) -> None:
    """根据颜色状态刷新商品状态。"""
    product_report["status"] = "fail" if any(
        item.get("status") == "fail" for item in product_report.get("items", [])
    ) else "pass"


def _summarize_report(report: dict[str, Any]) -> dict[str, Any]:
    """汇总报告：统计商品数、颜色数及 pass/fail 数量。

    参数:
        report: 完整报告字典。
    返回:
        汇总字典。
    """
    products = report.get("items", [])
    colors = [item for product in products for item in product.get("items", [])]
    summary = {
        "products": len(products),
        "items": len(colors),
        "passed": sum(1 for item in colors if item.get("status") == "pass"),
        "failed": sum(1 for item in colors if item.get("status") == "fail"),
    }
    retry_summary = report.get("fill_model_retry", {})
    if retry_summary.get("queued"):
        summary["fill_model_retry"] = retry_summary
    return summary
