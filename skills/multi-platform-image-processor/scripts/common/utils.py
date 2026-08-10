from __future__ import annotations

import json
import logging
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image


logger = logging.getLogger(__name__)

图片后缀 = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}

平台目录名 = {
    "tmall": "天猫通用版",
    "cbme": "CBME",
    "jd": "京东",
    "vip": "唯品会",
    "fengxiang-aikucun": "蜂享家＋爱库存",
    "offsite": "站外通用版",
}

全部平台 = list(平台目录名)


def build_platform_directory_names(product_code: str, product_name: str) -> dict[str, str]:
    """构造当前产品的六平台输出目录名。

    参数：
        product_code：Excel 确认的产品货号。
        product_name：Excel 确认的产品名称。
    返回值：
        包含六个平台键与实际输出目录名的字典。
    """
    code = re.sub(r'[<>:"/\\|?*]', " ", product_code).strip()
    name = re.sub(r'[<>:"/\\|?*]', " ", product_name).strip()
    code = " ".join(code.split())
    name = " ".join(name.split())
    if not code or not name:
        raise RuntimeError("生成京东目录名需要 Excel 中的产品货号和产品名称")
    directory_names = dict(平台目录名)
    directory_names["jd"] = f"{code} {name}-京东"
    return directory_names


def resolve_path(value: str | Path | None) -> Path | None:
    if value is None:
        return None
    return Path(value).expanduser().resolve()


def ensure_dir(path: str | Path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def is_image(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in 图片后缀


def natural_sort_key(path: Path) -> tuple:
    parts = []
    for token in re.split(r"(\d+)", path.as_posix().casefold()):
        if not token:
            continue
        if token.isdigit():
            parts.append((0, int(token), token))
        else:
            parts.append((1, token, ""))
    return tuple(parts)


def list_images(path: Path | None, recursive: bool = False) -> list[Path]:
    if path is None or not path.exists():
        return []
    iterator = path.rglob("*") if recursive else path.iterdir()
    return sorted([p for p in iterator if is_image(p)], key=natural_sort_key)


def safe_relative_path(path: Path, root: Path | None = None) -> str:
    try:
        if root:
            return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        pass
    return str(path)


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    idx = 2
    while True:
        candidate = parent / f"{stem}_{idx}{suffix}"
        if not candidate.exists():
            return candidate
        idx += 1


def new_report(source: Path, template: Path | None, output: Path, platform: str) -> dict[str, Any]:
    """创建本次处理使用的初始报告。

    参数：
        source：输入图片包路径。
        template：可选的平台目录模板路径。
        output：输出目录路径。
        platform：目标平台参数。
    返回值：
        包含处理配置、统计、追溯信息和异常列表的报告数据。
    """
    return {
        "处理配置": {
            "源目录": str(source),
            "模板目录": str(template) if template else "",
            "输出目录": str(output),
            "平台参数": platform,
            "开始时间": datetime.now().isoformat(timespec="seconds"),
        },
        "输入包检测": {},
        "素材扫描": {},
        "平台结果": {},
        "图片记录": [],
        "图片统计": {},
        "PNG压缩统计": {},
        "追溯文件": {},
        "Agent复核建议": [],
        "警告": [],
        "风险": [],
        "失败项": [],
        "汇总": {},
    }


def add_warning(report: dict[str, Any], message: str, **extra: Any) -> None:
    item = {"信息": message}
    item.update(extra)
    report["警告"].append(item)


def add_risk(report: dict[str, Any], message: str, **extra: Any) -> None:
    item = {"信息": message}
    item.update(extra)
    report["风险"].append(item)


def add_failure(report: dict[str, Any], message: str, **extra: Any) -> None:
    item = {"信息": message}
    item.update(extra)
    report["失败项"].append(item)


def add_review_suggestion(report: dict[str, Any], task: str, paths: list[Path], reason: str) -> None:
    output_dir = Path(report.get("处理配置", {}).get("输出目录", ""))
    short_paths = []
    for p in paths:
        try:
            short_paths.append(str(p.relative_to(output_dir)))
        except ValueError:
            short_paths.append(p.name)
    report["Agent复核建议"].append(
        {
            "任务名称": task,
            "图片路径": short_paths,
            "原因": reason,
        }
    )


def image_info(path: Path) -> dict[str, Any]:
    try:
        with Image.open(path) as img:
            return {
                "尺寸": [img.width, img.height],
                "格式": img.format or path.suffix.lstrip(".").upper(),
                "模式": img.mode,
                "大小KB": round(path.stat().st_size / 1024, 2),
                "有透明通道": bool(img.mode in ("RGBA", "LA") or "transparency" in img.info),
            }
    except Exception as exc:
        return {
            "尺寸": [],
            "格式": "",
            "模式": "",
            "大小KB": round(path.stat().st_size / 1024, 2) if path.exists() else 0,
            "有透明通道": False,
            "读取错误": str(exc),
        }


def add_image_record(
    report: dict[str, Any],
    source: Path | None,
    output: Path,
    platform: str,
    usage: str,
    actions: list[str] | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """记录单张输出图片的处理结果。

    参数：
        report：当前运行的报告数据。
        source：源图片路径。
        output：输出图片路径。
        platform：目标平台名称。
        usage：图片用途。
        actions：已执行的处理动作。
        details：需要写入逐图明细的附加结构化信息。
    返回值：
        无返回值。
    """
    info = image_info(output) if output.exists() else {}
    record = {
        "平台": platform,
        "用途": usage,
        "源文件": str(source) if source else "",
        "输出文件": str(output),
        "处理动作": actions or [],
        "处理结果": "成功",
        **info,
        **(details or {}),
    }
    report["图片记录"].append(record)
    logger.info(
        "图片处理完成 source=%r output=%r size=%r format=%s size_kb=%s actions=%r",
        record["源文件"],
        record["输出文件"],
        record.get("尺寸", []),
        record.get("格式", ""),
        record.get("大小KB", 0),
        record["处理动作"],
        extra={
            "platform": platform,
            "stage": "图片处理",
            "event": "图片完成",
            "status": "success",
        },
    )


def add_platform_result(report: dict[str, Any], platform: str, output_dir: Path) -> None:
    images = list_images(output_dir, recursive=True)
    empty_dirs = []
    for directory in output_dir.rglob("*"):
        if directory.is_dir() and not any(directory.iterdir()):
            empty_dirs.append(str(directory))
    report["平台结果"][platform] = {
        "输出路径": str(output_dir),
        "输出图片数量": len(images),
        "保留空目录": empty_dirs,
    }


def copy_template_empty_dirs(template_root: Path | None, platform_name: str, output_platform_dir: Path) -> None:
    if template_root is None or not template_root.exists():
        return
    candidates = [template_root / platform_name]
    candidates.extend([p for p in template_root.iterdir() if p.is_dir() and p.name == platform_name])
    source = next((p for p in candidates if p.exists()), None)
    if source is None:
        return
    for directory in source.rglob("*"):
        if directory.is_dir():
            relative = directory.relative_to(source)
            (output_platform_dir / relative).mkdir(parents=True, exist_ok=True)


def copy_file_original(source: Path, output: Path, report: dict[str, Any], platform: str, usage: str) -> Path | None:
    try:
        ensure_dir(output.parent)
        target = unique_path(output)
        shutil.copy2(source, target)
        add_image_record(report, source, target, platform, usage, ["原样复制"])
        return target
    except Exception as exc:
        add_failure(report, "复制文件失败", 源文件=str(source), 输出文件=str(output), 错误=str(exc))
        return None


def write_json(path: Path, data: dict[str, Any]) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def build_image_statistics(records: list[dict[str, Any]]) -> dict[str, Any]:
    """统计逐图明细中的平台和用途数量。

    参数：
        records：本次运行产生的逐图处理记录。
    返回值：
        包含图片总数及各平台用途数量的精简统计。
    """
    platforms: dict[str, dict[str, Any]] = {}
    for record in records:
        platform = record.get("平台", "未知")
        usage = record.get("用途", "未知")
        platform_statistics = platforms.setdefault(platform, {"总数": 0, "按用途": {}})
        platform_statistics["总数"] += 1
        usages = platform_statistics["按用途"]
        usages[usage] = usages.get(usage, 0) + 1
    return {"总数": len(records), "按平台": platforms}


def build_png_compression_statistics(records: list[dict[str, Any]]) -> dict[str, int]:
    """统计逐图明细中的 PNG 压缩结果。

    参数：
        records：本次运行产生的逐图处理记录。
    返回值：
        PNG 处理总数及四类压缩状态数量。
    """
    statistics = {
        "处理图片数": 0,
        "成功": 0,
        "保留原图": 0,
        "超出限制": 0,
        "执行失败": 0,
    }
    for record in records:
        compression = record.get("PNG压缩")
        if not isinstance(compression, dict):
            continue
        status = compression.get("状态")
        statistics["处理图片数"] += 1
        if status in statistics and status != "处理图片数":
            statistics[status] += 1
    return statistics


def finalize_report_summary(report: dict[str, Any], total_images: int | None = None) -> None:
    """补充主报告的结束时间和汇总计数。

    参数：
        report：需要写出的精简主报告。
        total_images：逐图明细总数；未提供时读取图片统计中的总数。
    返回值：
        无返回值。
    """
    report["处理配置"]["结束时间"] = datetime.now().isoformat(timespec="seconds")
    if total_images is None:
        total_images = int(report.get("图片统计", {}).get("总数", 0))

    report["汇总"] = {
        "平台数": len(report.get("平台结果", {})),
        "图片数": total_images,
        "Agent复核建议数": len(report.get("Agent复核建议", [])),
        "警告数": len(report.get("警告", [])),
        "风险数": len(report.get("风险", [])),
        "失败数": len(report.get("失败项", [])),
    }
