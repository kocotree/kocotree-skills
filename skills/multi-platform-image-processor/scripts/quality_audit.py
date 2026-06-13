from __future__ import annotations

import re
from pathlib import Path

from common import list_images, image_info, add_warning


def run_quality_audit(output_root: Path, platforms: list[str], report: dict) -> None:
    for platform in platforms:
        if platform == "tmall":
            _audit_tmall(output_root / "天猫通用版", report)
        elif platform == "cbme":
            _audit_cbme(output_root / "CBME", report)
        elif platform == "jd":
            _audit_jd(output_root / "京东", report)
        elif platform == "vip":
            _audit_vip(output_root / "唯品会", report)
        elif platform == "fengxiang-aikucun":
            _audit_fengxiang(output_root / "蜂享家＋爱库存", report)
        elif platform == "offsite":
            _audit_offsite(output_root / "站外通用版", report)


def _check_file_size(path: Path, max_kb: int, report: dict) -> None:
    if path.exists() and path.stat().st_size > max_kb * 1024:
        add_warning(report, "文件大小超过平台限制", 文件=str(path), 限制KB=max_kb, 实际KB=round(path.stat().st_size / 1024, 2))


def _check_dimensions(path: Path, width: int | None, height: int | None, report: dict, message: str) -> None:
    info = image_info(path)
    size = info.get("尺寸") or []
    if len(size) != 2:
        add_warning(report, "无法读取图片尺寸", 文件=str(path))
        return
    ok = (width is None or size[0] == width) and (height is None or size[1] == height)
    if not ok:
        add_warning(report, message, 文件=str(path), 实际尺寸=size, 期望宽=width, 期望高=height)


def _check_detail_sequence(directory: Path, prefix: int, report: dict) -> None:
    images = list_images(directory)
    numbers = []
    for path in images:
        if path.stem.isdigit():
            numbers.append(int(path.stem))
    if numbers and numbers != list(range(prefix, prefix + len(numbers))):
        add_warning(report, "详情页命名不连续", 目录=str(directory), 实际编号=numbers)


def _check_fengxiang_names(directory: Path, report: dict) -> None:
    images = list_images(directory)
    expected = [f"详情图-{i:02d}" for i in range(1, len(images) + 1)]
    actual = [p.stem for p in images]
    if actual != expected:
        add_warning(report, "蜂享家＋爱库存详情页命名不连续", 目录=str(directory), 实际=actual, 期望=expected)


def _audit_tmall(root: Path, report: dict) -> None:
    for path in list_images(root, recursive=True):
        _check_file_size(path, 500, report)
    for path in list_images(root / "790详情页"):
        _check_dimensions(path, 790, None, report, "天猫详情页宽度不符合790px")
        info = image_info(path)
        if len(info.get("尺寸", [])) == 2 and info["尺寸"][1] > 1600:
            add_warning(report, "天猫详情页高度超过1600px", 文件=str(path), 实际高度=info["尺寸"][1])
    _check_detail_sequence(root / "790详情页", 601, report)


def _audit_cbme(root: Path, report: dict) -> None:
    for path in list_images(root, recursive=True):
        _check_file_size(path, 500, report)
    for path in list_images(root / "750主图"):
        _check_dimensions(path, 750, 750, report, "CBME主图尺寸不符合750x750")
    for path in list_images(root / "750详情页"):
        _check_dimensions(path, 750, None, report, "CBME详情页宽度不符合750px")
    _check_detail_sequence(root / "750详情页", 601, report)


def _audit_jd(root: Path, report: dict) -> None:
    for path in list_images(root, recursive=True):
        _check_file_size(path, 500, report)
    for path in list_images(root / "透明图"):
        _check_dimensions(path, 800, 800, report, "京东透明图尺寸不符合800x800")
        info = image_info(path)
        if not info.get("有透明通道"):
            add_warning(report, "京东透明图未检测到透明通道", 文件=str(path))
    _check_detail_sequence(root / "790详情页", 601, report)


def _audit_vip(root: Path, report: dict) -> None:
    for path in list_images(root, recursive=True):
        _check_file_size(path, 500, report)
    for path in list_images(root / "1200主图"):
        _check_dimensions(path, 1200, 1200, report, "唯品会主图尺寸不符合1200x1200")
    for path in list_images(root / "1200透明图"):
        info = image_info(path)
        if 1200 not in (info.get("尺寸") or []):
            add_warning(report, "唯品会透明图没有任一边为1200px", 文件=str(path), 实际尺寸=info.get("尺寸"))
        if not info.get("有透明通道"):
            add_warning(report, "唯品会透明图未检测到透明通道", 文件=str(path))
    _check_detail_sequence(root / "750详情页", 601, report)


def _audit_fengxiang(root: Path, report: dict) -> None:
    for path in list_images(root, recursive=True):
        _check_file_size(path, 1024 if "790详情页" in str(path.parent) else 500, report)
    detail = list_images(root / "790详情页")
    if len(detail) > 20:
        add_warning(report, "蜂享家＋爱库存详情页数量超过20张", 数量=len(detail))
    for path in detail:
        _check_dimensions(path, 790, None, report, "蜂享家＋爱库存详情页宽度不符合790px")
        info = image_info(path)
        if len(info.get("尺寸", [])) == 2 and info["尺寸"][1] > 4800:
            add_warning(report, "蜂享家＋爱库存详情页高度超过4800px", 文件=str(path), 实际高度=info["尺寸"][1])
    _check_fengxiang_names(root / "790详情页", report)


def _audit_offsite(root: Path, report: dict) -> None:
    for path in list_images(root, recursive=True):
        _check_file_size(path, 500, report)
