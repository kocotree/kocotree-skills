from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image


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


def list_images(path: Path | None, recursive: bool = False) -> list[Path]:
    if path is None or not path.exists():
        return []
    iterator = path.rglob("*") if recursive else path.iterdir()
    return sorted([p for p in iterator if is_image(p)], key=lambda p: p.name.lower())


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
    return {
        "处理配置": {
            "源目录": str(source),
            "模板目录": str(template) if template else "",
            "输出目录": str(output),
            "平台参数": platform,
            "开始时间": datetime.now().isoformat(timespec="seconds"),
        },
        "素材扫描": {},
        "平台结果": {},
        "图片记录": [],
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
    report["Agent复核建议"].append(
        {
            "任务名称": task,
            "图片路径": [str(p) for p in paths],
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
) -> None:
    info = image_info(output) if output.exists() else {}
    report["图片记录"].append(
        {
            "平台": platform,
            "用途": usage,
            "源文件": str(source) if source else "",
            "输出文件": str(output),
            "处理动作": actions or [],
            **info,
        }
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


def finalize_report_summary(report: dict[str, Any]) -> None:
    report["处理配置"]["结束时间"] = datetime.now().isoformat(timespec="seconds")
    report["汇总"] = {
        "平台数": len(report.get("平台结果", {})),
        "图片数": len(report.get("图片记录", [])),
        "Agent复核建议数": len(report.get("Agent复核建议", [])),
        "警告数": len(report.get("警告", [])),
        "风险数": len(report.get("风险", [])),
        "失败数": len(report.get("失败项", [])),
    }
