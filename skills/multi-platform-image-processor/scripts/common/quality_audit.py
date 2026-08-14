from __future__ import annotations

from pathlib import Path

from .scan_source_pack import get_sku800_recursive, has_gift_sku_branches, resolve_sku_root
from .utils import list_images, image_info, add_failure, add_warning, 平台目录名


def run_quality_audit(
    report: dict,
    platform_directories: dict[str, Path],
) -> None:
    """按平台实际输出目录执行图片质检。

    参数：
        report：用于记录质检结果的报告。
        platform_directories：平台键与实际输出目录映射。
    返回值：
        无返回值。
    """
    for platform in 平台目录名:
        if platform == "tmall":
            _audit_tmall(platform_directories[platform], report)
        elif platform == "cbme":
            _audit_cbme(platform_directories[platform], report)
        elif platform == "jd":
            _audit_jd(platform_directories[platform], report)
        elif platform == "vip":
            _audit_vip(platform_directories[platform], report)
        elif platform == "fengxiang-aikucun":
            _audit_fengxiang(platform_directories[platform], report)
        elif platform == "offsite":
            _audit_offsite(platform_directories[platform], report)


def audit_gift_sku_outputs(
    source_root: Path,
    platform_directories: dict[str, Path],
    report: dict,
) -> None:
    """核对赠品 SKU 的平台分支和图片数量。

    功能说明：验证天猫完整保留源 SKU 相对路径，蜂享家＋爱库存只保留
    两个分支的 800 图，并确认站外输出记录全部来自无赠品 800 图。
    参数：
        source_root：产品素材根目录。
        platform_directories：平台键与实际输出目录映射。
        report：用于记录质检结果的报告。
    返回值：
        无返回值。
    """
    if not has_gift_sku_branches(source_root):
        return

    sku_root = resolve_sku_root(source_root)
    tmall_root = platform_directories["tmall"] / "sku"
    fengxiang_root = platform_directories["fengxiang-aikucun"] / "800sku"
    _check_relative_image_set(
        {path.relative_to(sku_root).with_suffix(".jpg") for path in list_images(sku_root, recursive=True)},
        tmall_root,
        "天猫赠品SKU目录与源目录不一致",
        report,
    )
    _check_relative_image_set(
        {path.relative_to(sku_root).with_suffix(".jpg") for path in get_sku800_recursive(source_root)},
        fengxiang_root,
        "蜂享家＋爱库存赠品SKU目录与源目录不一致",
        report,
    )
    for size_name in ("800", "1440"):
        if (tmall_root / size_name).exists():
            add_failure(report, "天猫赠品SKU存在多余顶层尺寸目录", 目录=str(tmall_root / size_name))

    invalid_records = []
    for record in report.get("图片记录", []):
        if record.get("平台") != "站外通用版" or record.get("用途") != "sku":
            continue
        source = Path(record.get("源文件", ""))
        try:
            parts = source.relative_to(sku_root).parts
        except ValueError:
            parts = source.parts
        normalized = {
            part.casefold().replace("×", "x").replace(" ", "")
            for part in parts
        }
        if "无赠品" not in normalized or not normalized.intersection({"800", "800x800"}):
            invalid_records.append(str(source))
    if invalid_records:
        add_failure(report, "站外赠品SKU来源不是无赠品800分支", 源文件=invalid_records)


def _check_relative_image_set(
    expected: set[Path],
    output_root: Path,
    message: str,
    report: dict,
) -> None:
    """比较预期与实际图片相对路径集合。"""
    actual = {path.relative_to(output_root) for path in list_images(output_root, recursive=True)}
    expected_keys = {path.as_posix().casefold() for path in expected}
    actual_keys = {path.as_posix().casefold() for path in actual}
    if expected_keys != actual_keys:
        add_failure(
            report,
            message,
            缺少=sorted(expected_keys - actual_keys),
            多余=sorted(actual_keys - expected_keys),
        )


def _check_file_size(path: Path, max_kb: int, report: dict) -> None:
    if path.exists() and path.stat().st_size > max_kb * 1024:
        add_failure(report, "文件大小超过平台限制", 文件=str(path), 限制KB=max_kb, 实际KB=round(path.stat().st_size / 1024, 2))


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
    _check_detail_sequence(root / "详情页", 601, report)


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
    for path in list_images(root / "sku"):
        _check_dimensions(path, 800, 800, report, "站外SKU去字图尺寸不符合800x800")
        info = image_info(path)
        if info.get("格式") != "JPEG":
            add_warning(report, "站外SKU去字图格式不是JPG", 文件=str(path), 实际格式=info.get("格式"))
