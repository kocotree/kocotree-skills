from __future__ import annotations

import argparse
from difflib import SequenceMatcher
import io
import json
import re
import shutil
import sys
import uuid
from pathlib import Path

from PIL import Image, ImageOps


MAX_BYTES = 500 * 1024
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
PRODUCT_CODE_RE = re.compile(r"(?i)([a-z]{1,8}[-_]?\d{3,})")


def natural_key(path: Path) -> tuple:
    return tuple(int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", str(path)))


def list_images(directory: Path, recursive: bool = False) -> list[Path]:
    if not directory.is_dir():
        return []
    candidates = directory.rglob("*") if recursive else directory.iterdir()
    return sorted(
        (path for path in candidates if path.is_file() and path.suffix.casefold() in IMAGE_SUFFIXES),
        key=natural_key,
    )


def find_casefold_dir(root: Path, name: str) -> Path | None:
    matches = [child for child in root.iterdir() if child.is_dir() and child.name.casefold() == name.casefold()]
    return matches[0] if len(matches) == 1 else None


def resolve_detail_source_dir(detail_root: Path) -> Path:
    preferred = find_casefold_dir(detail_root, "790")
    if preferred is not None and list_images(preferred, recursive=True):
        return preferred
    fallback = find_casefold_dir(detail_root, "images")
    if fallback is not None and list_images(fallback, recursive=True):
        return fallback
    if list_images(detail_root):
        return detail_root
    raise FileNotFoundError(
        f"详情页缺少图片来源：{detail_root / '790'}、{detail_root / 'images'} 和详情页根目录都没有图片"
    )


def list_resolved_detail_images(detail_root: Path, resolved_source: Path) -> list[Path]:
    return list_images(resolved_source, recursive=resolved_source != detail_root)


def walk_dirs_limited(root: Path, max_depth: int) -> list[Path]:
    if not root.is_dir():
        return []
    result: list[Path] = []
    pending = [(root, 0)]
    while pending:
        current, depth = pending.pop()
        if depth >= max_depth:
            continue
        try:
            children = list(current.iterdir())
        except OSError:
            continue
        for path in children:
            if path.is_dir():
                result.append(path)
                pending.append((path, depth + 1))
    return result


def normalize_package_name(name: str) -> str:
    value = name.casefold().replace("－", "-").replace(" ", "")
    value = re.sub(r"-全平台.*$", "", value)
    return re.sub(r"(?:-优化|数据包|新款|改款)$", "", value)


def standalone_category(source: Path) -> tuple[str, str] | None:
    if source.name == "主图":
        return "主图", "主图"
    if source.name in {"详情页", "详情"}:
        return "详情页", "详情页"
    if source.name.casefold() == "sku":
        return "SKU", "sku"
    return None


def product_code(name: str) -> str | None:
    match = PRODUCT_CODE_RE.search(name)
    return match.group(1).upper() if match else None


def product_label(name: str) -> str:
    value = name.replace("－", "-").strip()
    value = re.sub(r"-全平台.*$", "", value, flags=re.IGNORECASE)
    value = re.sub(r"-(?:优化|数据包|新款|改款)$", "", value, flags=re.IGNORECASE).strip(" -_")
    match = PRODUCT_CODE_RE.search(value)
    if not match:
        raise ValueError(f"目录名称中没有可识别的款号：{name}")
    code = match.group(1).upper()
    remainder = (value[:match.start()] + " " + value[match.end():]).strip(" -_")
    remainder = re.sub(r"\s+", " ", remainder)
    return f"{code} {remainder}".strip()


def resolve_standalone_identity(source: Path) -> tuple[str, Path | None]:
    ancestors = [source.parent]
    if source.parent.parent != source.parent:
        ancestors.append(source.parent.parent)
    ancestor_with_code = next((path for path in ancestors if product_code(path.name)), None)
    expected_code = product_code(ancestor_with_code.name) if ancestor_with_code else None

    near_paths = [source.parent.resolve(), *walk_dirs_limited(source, 2), *walk_dirs_limited(source.parent, 1)]
    far_paths = [source.parent.parent.resolve(), *walk_dirs_limited(source.parent.parent, 2)]
    for paths in (near_paths, far_paths):
        candidates = list(dict.fromkeys(
            path.resolve() for path in paths
            if path != source
            and not path.name.endswith("-优化")
            and product_code(path.name)
            and "-全平台" in path.name.replace("－", "-")
        ))
        if expected_code:
            candidates = [path for path in candidates if product_code(path.name) == expected_code]
        if not candidates:
            continue
        codes = sorted({product_code(path.name) for path in candidates if product_code(path.name)})
        if len(codes) > 1:
            rendered = "\n".join(f"- {path}" for path in sorted(candidates, key=natural_key))
            raise RuntimeError(f"附近找到多个不同款号的全平台文件夹，无法唯一判断：\n{rendered}")
        labels = {product_label(path.name) for path in candidates}
        if len(labels) > 1:
            rendered = "\n".join(f"- {path}" for path in sorted(candidates, key=natural_key))
            raise RuntimeError(f"同一款号对应多个不同商品名称，无法唯一判断：\n{rendered}")
        chosen = min(candidates, key=lambda path: (len(path.parts), natural_key(path)))
        return labels.pop(), chosen
    if ancestor_with_code:
        return product_label(ancestor_with_code.name), None
    raise FileNotFoundError("无法从输入文件夹的同级、上级或下级唯一确定对应款号和名称")


def find_original_package(source: Path) -> Path:
    roots = [source, source.parent]
    if source.parent.parent != source.parent:
        roots.append(source.parent.parent)
    candidates: dict[Path, None] = {}
    for index, root in enumerate(roots):
        depth = 3 if index < 2 else 2
        if "-全平台" in root.name.replace("－", "-") and root != source:
            candidates[root.resolve()] = None
        for path in walk_dirs_limited(root, depth):
            if path == source or path.name.endswith("-优化"):
                continue
            if "-全平台" in path.name.replace("－", "-"):
                candidates[path.resolve()] = None
    values = sorted(candidates, key=lambda path: (len(path.parts), natural_key(path)))
    if not values:
        raise FileNotFoundError("未找到原款全平台文件夹；请提供原款文件路径后使用 --original-package 继续")
    source_name = normalize_package_name(source.name)
    matched = [path for path in values if normalize_package_name(path.name) == source_name]
    if len(matched) == 1:
        return matched[0]
    scored = sorted(
        (
            SequenceMatcher(None, source_name, normalize_package_name(path.name)).ratio(),
            path,
        )
        for path in values
    )
    best_score, best_path = scored[-1]
    second_score = scored[-2][0] if len(scored) > 1 else 0.0
    if best_score >= 0.65 and best_score - second_score >= 0.10:
        return best_path
    if best_score < 0.65:
        raise FileNotFoundError("未找到原款全平台文件夹：附近候选与新数据包货号或名称不相符；请提供原款文件路径后使用 --original-package 继续")
    rendered = "\n".join(f"- {path}" for path in values)
    raise RuntimeError(f"找到多个原款全平台候选，无法唯一判断：\n{rendered}")


def find_original_aik_detail(original_package: Path) -> Path:
    accepted = {"蜂享家+爱库存", "爱库存+蜂享家", "akc+蜂享家"}
    platform_dirs = [
        path for path in [original_package, *walk_dirs_limited(original_package, 4)]
        if path.name.casefold().replace("＋", "+").replace(" ", "") in accepted
    ]
    detail_dirs: list[Path] = []
    for platform in platform_dirs:
        preferred = platform / "790详情页"
        if preferred.is_dir() and list_images(preferred, recursive=True):
            detail_dirs.append(preferred)
        elif list_images(platform):
            detail_dirs.append(platform)
    unique = list(dict.fromkeys(path.resolve() for path in detail_dirs))
    if len(unique) == 1:
        return unique[0]
    if not unique:
        raise FileNotFoundError(f"原款全平台包内未找到爱库存+蜂享家完整详情页：{original_package}")
    rendered = "\n".join(f"- {path}" for path in unique)
    raise RuntimeError(f"原款包内存在多个爱库存+蜂享家详情目录，无法唯一判断：\n{rendered}")


def load_replacement_map(path: Path, source_root: Path, original_detail: Path) -> list[dict]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"替换定位 JSON 无法读取：{exc}") from exc
    items = payload.get("替换")
    if not isinstance(items, list) or not items:
        raise RuntimeError("替换定位 JSON 缺少非空的“替换”列表")
    affected_items = payload.get("受影响原图")
    if not isinstance(affected_items, list) or not affected_items or not all(isinstance(value, str) for value in affected_items):
        raise RuntimeError("替换定位 JSON 缺少非空的“受影响原图”文件名列表")
    parsed = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise RuntimeError(f"替换定位第 {index} 项格式错误")
        new_path = (source_root / str(item.get("新图", ""))).resolve()
        old_path = (original_detail / str(item.get("原图", ""))).resolve()
        box = item.get("区域")
        operation = str(item.get("操作", "替换"))
        if operation not in {"替换", "插入"}:
            raise RuntimeError(f"替换定位第 {index} 项操作必须是“替换”或“插入”")
        if not new_path.is_file() or source_root not in new_path.parents:
            raise RuntimeError(f"替换定位第 {index} 项新图无效：{new_path}")
        if not old_path.is_file() or original_detail not in old_path.parents:
            raise RuntimeError(f"替换定位第 {index} 项原图无效：{old_path}")
        if not isinstance(box, list) or len(box) != 4 or not all(isinstance(value, int) for value in box):
            raise RuntimeError(f"替换定位第 {index} 项区域必须是四个整数")
        left, top, right, bottom = box
        invalid_box = left < 0 or top < 0 or right <= left or bottom < top
        if operation == "替换" and bottom == top:
            invalid_box = True
        if operation == "插入" and bottom != top:
            invalid_box = True
        if invalid_box:
            raise RuntimeError(f"替换定位第 {index} 项区域无效：{box}")
        parsed.append({"新图": new_path, "原图": old_path, "区域": (left, top, right, bottom), "操作": operation})
    confirmed = {(original_detail / value).resolve() for value in affected_items}
    mapped = {item["原图"].resolve() for item in parsed}
    invalid_confirmed = [path for path in confirmed if not path.is_file() or original_detail not in path.parents]
    if invalid_confirmed:
        raise RuntimeError(f"受影响原图列表包含无效文件：{invalid_confirmed}")
    if confirmed != mapped:
        extra = sorted(confirmed - mapped)
        missing = sorted(mapped - confirmed)
        raise RuntimeError(f"受影响原图必须与实际替换目标完全一致；未发生替换却被列入={extra}，发生替换但未确认={missing}")
    return parsed


def open_rgb(path: Path) -> Image.Image:
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source)
        if image.mode in {"RGBA", "LA"} or (image.mode == "P" and "transparency" in image.info):
            rgba = image.convert("RGBA")
            canvas = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
            canvas.alpha_composite(rgba)
            return canvas.convert("RGB")
        return image.convert("RGB")


def unique_jpg_path(directory: Path, stem: str) -> Path:
    candidate = directory / f"{stem}.jpg"
    index = 2
    while candidate.exists():
        candidate = directory / f"{stem}_{index}.jpg"
        index += 1
    return candidate


def save_jpg_under(image: Image.Image, output: Path, max_bytes: int = MAX_BYTES) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    rgb = image.convert("RGB")
    for quality in (95, 92, 90, 88, 85, 82, 80, 76, 72, 68, 64, 60, 55, 50, 45, 40, 35, 30, 25, 20, 15, 10, 5, 1):
        buffer = io.BytesIO()
        rgb.save(buffer, "JPEG", quality=quality, optimize=True, progressive=True, subsampling=2)
        if buffer.tell() <= max_bytes:
            output.write_bytes(buffer.getvalue())
            return
    raise RuntimeError(f"无法在保持像素尺寸的前提下压缩到 {max_bytes} 字节以内：{output}")


def fit_canvas(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    fitted = ImageOps.contain(image, size, Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", size, (255, 255, 255))
    canvas.paste(fitted, ((size[0] - fitted.width) // 2, (size[1] - fitted.height) // 2))
    return canvas


def scale_width(image: Image.Image, width: int) -> Image.Image:
    height = max(1, round(image.height * width / image.width))
    return image.resize((width, height), Image.Resampling.LANCZOS)


def process_to_canvas(source: Path, output_dir: Path, size: tuple[int, int]) -> Path:
    output = unique_jpg_path(output_dir, source.stem)
    save_jpg_under(fit_canvas(open_rgb(source), size), output)
    return output


def process_original_jpg(source: Path, output: Path) -> Path:
    save_jpg_under(open_rgb(source), output)
    return output


def build_main(source: Path, output: Path, summary: dict) -> None:
    output.mkdir(parents=True, exist_ok=True)
    preserved_sources = {
        "800": source / "800",
        "750": source / "750",
    }
    targets = {
        "1440": (source / "800", (1440, 1440)),
        "1080": (source / "750", (1080, 1440)),
        "750正": (source / "800", (750, 750)),
        "1920": (source / "750", (1440, 1920)),
    }
    all_images = list_images(source, recursive=True)
    if len(all_images) == 1:
        image = all_images[0]
        relative = image.relative_to(source)
        if relative.parts and relative.parts[0] in preserved_sources:
            preserved_name = relative.parts[0]
            try:
                process_original_jpg(image, output / f"{preserved_name}.jpg")
                summary["images"] += 1
            except Exception as exc:
                summary["failures"].append(
                    f"单图主图原尺寸保留失败：{image} -> {preserved_name}.jpg：{exc}"
                )
        for name, (_, size) in targets.items():
            try:
                save_jpg_under(fit_canvas(open_rgb(image), size), output / f"{name}.jpg")
                summary["images"] += 1
            except Exception as exc:
                summary["failures"].append(f"单图主图处理失败：{image} -> {name}.jpg：{exc}")
        return
    for name, source_dir in preserved_sources.items():
        target_dir = output / name
        target_dir.mkdir(parents=True, exist_ok=True)
        for image in list_images(source_dir):
            try:
                process_original_jpg(image, unique_jpg_path(target_dir, image.stem))
                summary["images"] += 1
            except Exception as exc:
                summary["failures"].append(f"主图原尺寸保留失败：{image}：{exc}")

    for name, (source_dir, size) in targets.items():
        target_dir = output / name
        target_dir.mkdir(parents=True, exist_ok=True)
        images = list_images(source_dir)
        if not images:
            summary["warnings"].append(f"主图来源为空或不存在：{source_dir}")
        for image in images:
            try:
                process_to_canvas(image, target_dir, size)
                summary["images"] += 1
            except Exception as exc:
                summary["failures"].append(f"主图处理失败：{image}：{exc}")


def split_height(image: Image.Image, limit: int) -> list[Image.Image]:
    if image.height <= limit:
        return [image]
    return [image.crop((0, top, image.width, min(image.height, top + limit))) for top in range(0, image.height, limit)]


def build_detail(source: Path, output: Path, summary: dict) -> None:
    detail_sources = resolve_detail_source_dir(source)
    all_images = list_resolved_detail_images(source, detail_sources)
    if len(all_images) == 1:
        output.mkdir(parents=True, exist_ok=True)
        path = all_images[0]
        try:
            image = open_rgb(path)
            save_jpg_under(scale_width(image, 790), output / "790.jpg")
            summary["images"] += 1
            save_jpg_under(scale_width(image, 750), output / "750.jpg")
            summary["images"] += 1
            pieces = split_height(scale_width(image, 790), 4800)
            for index, piece in enumerate(pieces, start=1):
                suffix = "" if index == 1 else f"_{index}"
                save_jpg_under(piece, output / f"爱库存+蜂享家{suffix}.jpg")
                summary["images"] += 1
        except Exception as exc:
            summary["failures"].append(f"单图详情页处理失败：{path}：{exc}")
        return
    output_790 = output / "790"
    output_750 = output / "750"
    output_long = output / "爱库存+蜂享家"
    output_790.mkdir(parents=True, exist_ok=True)
    output_750.mkdir(parents=True, exist_ok=True)
    output_long.mkdir(parents=True, exist_ok=True)
    sources = list_resolved_detail_images(source, detail_sources)
    if not sources:
        summary["warnings"].append(f"详情页来源目录为空：{detail_sources}")
        return

    scaled_790: list[Image.Image] = []
    for path in sources:
        try:
            image = open_rgb(path)
            out_790 = unique_jpg_path(output_790, path.stem)
            save_jpg_under(scale_width(image, 790), out_790)
            summary["images"] += 1
            out_750 = unique_jpg_path(output_750, path.stem)
            save_jpg_under(scale_width(image, 750), out_750)
            summary["images"] += 1
            scaled_790.extend(split_height(scale_width(image, 790), 4800))
        except Exception as exc:
            summary["failures"].append(f"详情页处理失败：{path}：{exc}")

    groups: list[list[Image.Image]] = []
    current: list[Image.Image] = []
    current_height = 0
    for image in scaled_790:
        if current and current_height + image.height > 4800:
            groups.append(current)
            current = []
            current_height = 0
        current.append(image)
        current_height += image.height
    if current:
        groups.append(current)
    if len(groups) > 20:
        summary["warnings"].append(f"爱库存+蜂享家详情页共 {len(groups)} 张，超过 20 张限制，已完整输出")
    for index, group in enumerate(groups, start=1):
        canvas = Image.new("RGB", (790, sum(image.height for image in group)), (255, 255, 255))
        top = 0
        for image in group:
            canvas.paste(image, (0, top))
            top += image.height
        save_jpg_under(canvas, output_long / f"详情图-{index:02d}.jpg")
        summary["images"] += 1


def build_partial_detail(
    source_root: Path,
    detail_source: Path,
    output: Path,
    original_detail: Path,
    replacement_map: Path,
    summary: dict,
) -> None:
    resolved_detail_source = resolve_detail_source_dir(detail_source)
    changed = list_resolved_detail_images(detail_source, resolved_detail_source)
    if not changed:
        raise RuntimeError("局部改款模式至少需要一张修改详情图")

    if len(changed) == 1:
        output.mkdir(parents=True, exist_ok=True)
        try:
            image = open_rgb(changed[0])
            save_jpg_under(scale_width(image, 790), output / "790.jpg")
            summary["images"] += 1
            save_jpg_under(scale_width(image, 750), output / "750.jpg")
            summary["images"] += 1
        except Exception as exc:
            summary["failures"].append(f"局部改款 790/750 详情生成失败：{changed[0]}：{exc}")
    else:
        output_790 = output / "790"
        output_750 = output / "750"
        output_790.mkdir(parents=True, exist_ok=True)
        output_750.mkdir(parents=True, exist_ok=True)
        for image_path in changed:
            try:
                image = open_rgb(image_path)
                save_jpg_under(scale_width(image, 790), unique_jpg_path(output_790, image_path.stem))
                summary["images"] += 1
                save_jpg_under(scale_width(image, 750), unique_jpg_path(output_750, image_path.stem))
                summary["images"] += 1
            except Exception as exc:
                summary["failures"].append(f"局部改款 790/750 详情生成失败：{image_path}：{exc}")

    mappings = load_replacement_map(replacement_map, source_root, original_detail)
    mapped_new = [item["新图"].resolve() for item in mappings]
    missing = [path for path in changed if path.resolve() not in mapped_new]
    duplicates = {path for path in mapped_new if mapped_new.count(path) > 1}
    if missing or duplicates:
        raise RuntimeError(f"替换定位必须为每张新图提供且只提供一次映射；缺失={missing}，重复={sorted(duplicates)}")

    if not list_images(original_detail, recursive=True):
        raise RuntimeError(f"原款爱库存+蜂享家详情目录没有图片：{original_detail}")
    grouped: dict[Path, list[dict]] = {}
    for item in mappings:
        grouped.setdefault(item["原图"].resolve(), []).append(item)
    edited: dict[Path, Image.Image] = {}
    for target_path, target_items in grouped.items():
        original = open_rgb(target_path)
        boxes = sorted((item["区域"], item) for item in target_items)
        for (left, top, right, bottom), _ in boxes:
            if right > original.width or bottom > original.height:
                raise RuntimeError(f"替换区域超出原图范围：{target_path} {(left, top, right, bottom)}，原图={original.size}")
        for index in range(1, len(boxes)):
            previous = boxes[index - 1][0]
            current = boxes[index][0]
            if previous[3] > previous[1] and current[3] > current[1] and current[1] < previous[3] and current[0] < previous[2] and current[2] > previous[0]:
                raise RuntimeError(f"同一原图的替换区域相互重叠：{target_path} {previous} 与 {current}")

        target = original
        for (left, top, right, bottom), item in sorted(boxes, key=lambda pair: pair[0][1], reverse=True):
            replacement = open_rgb(item["新图"])
            if left == 0 and right == original.width:
                replacement = scale_width(replacement, original.width)
                canvas = Image.new(
                    "RGB",
                    (original.width, target.height - (bottom - top) + replacement.height),
                    (255, 255, 255),
                )
                canvas.paste(target.crop((0, 0, original.width, top)), (0, 0))
                canvas.paste(replacement, (0, top))
                canvas.paste(target.crop((0, bottom, original.width, target.height)), (0, top + replacement.height))
                target = canvas
            else:
                box_ratio = (right - left) / (bottom - top)
                replacement_ratio = replacement.width / replacement.height
                if abs(box_ratio - replacement_ratio) / box_ratio > 0.03:
                    raise RuntimeError(f"新图与替换区域宽高比差异超过 3%，停止拉伸粘贴：{item['新图']}")
                replacement = replacement.resize((right - left, bottom - top), Image.Resampling.LANCZOS)
                target.paste(replacement, (left, top))
        edited[target_path] = target

    if len(changed) == 1:
        original, result_image = next(iter(edited.items()))
        output_aik = output / "爱库存+蜂享家.jpg"
        try:
            save_jpg_under(result_image, output_aik)
            summary["images"] += 1
        except Exception as exc:
            summary["failures"].append(f"局部改款结果图输出失败：{original}：{exc}")
    else:
        output_aik = output / "爱库存+蜂享家"
        output_aik.mkdir(parents=True, exist_ok=True)
        for original, result_image in edited.items():
            try:
                target = output_aik / original.with_suffix(".jpg").name
                if target.exists():
                    raise RuntimeError(f"原款长图文件名冲突，无法保留原文件名：{target.name}")
                save_jpg_under(result_image, target)
                summary["images"] += 1
            except Exception as exc:
                summary["failures"].append(f"局部改款结果图输出失败：{original}：{exc}")
        expected_names = {original.with_suffix(".jpg").name for original in edited}
        actual_names = {path.name for path in list_images(output_aik)}
        if actual_names != expected_names:
            raise RuntimeError(
                f"爱库存+蜂享家结果必须只包含受影响原图；多余={sorted(actual_names - expected_names)}，"
                f"缺少={sorted(expected_names - actual_names)}"
            )
    summary["partial_detail"] = {
        "original_detail": str(original_detail),
        "replacement_count": len(mappings),
        "affected_originals": sorted(path.name for path in edited),
        "output": str(output_aik),
    }


def normalized_dir_name(name: str) -> str:
    return name.casefold().replace("×", "x").replace(" ", "")


def is_sku_size_dir(name: str) -> bool:
    return normalized_dir_name(name) in {"800", "800x800", "1400", "1440"}


def build_sku(source: Path, output: Path, summary: dict) -> None:
    all_images = list_images(source, recursive=True)
    if len(all_images) == 1:
        output.mkdir(parents=True, exist_ok=True)
        image = all_images[0]
        for name in ("通用sku", "京东", "唯品会"):
            try:
                process_original_jpg(image, output / f"{name}.jpg")
                summary["images"] += 1
            except Exception as exc:
                summary["failures"].append(f"单图 SKU 处理失败：{image} -> {name}.jpg：{exc}")
        return
    common = output / "通用sku"
    jd = output / "京东"
    vip = output / "唯品会"
    common.mkdir(parents=True, exist_ok=True)
    (jd / "1080sku").mkdir(parents=True, exist_ok=True)
    (jd / "1440sku").mkdir(parents=True, exist_ok=True)
    vip.mkdir(parents=True, exist_ok=True)

    business_branches = any(
        child.is_dir()
        and not is_sku_size_dir(child.name)
        and normalized_dir_name(child.name) != "sku组合"
        for child in source.iterdir()
    )
    if not business_branches:
        (common / "800").mkdir(parents=True, exist_ok=True)
        (common / "1440").mkdir(parents=True, exist_ok=True)
    images = all_images
    if not images:
        summary["warnings"].append(f"SKU 来源为空：{source}")
    for image in images:
        try:
            relative = image.relative_to(source)
            if len(relative.parts) == 1:
                relative = Path("800") / relative
            target_dir = common / relative.parent
            target = unique_jpg_path(target_dir, relative.stem)
            process_original_jpg(image, target)
            summary["images"] += 1
        except Exception as exc:
            summary["failures"].append(f"SKU 处理失败：{image}：{exc}")


def optimize_package(
    source: Path,
    *,
    partial_detail: bool = False,
    complete_detail: bool = False,
    original_package: Path | None = None,
    replacement_map: Path | None = None,
) -> tuple[Path, dict]:
    source = source.expanduser().resolve()
    if not source.is_dir():
        raise FileNotFoundError(f"输入文件夹不存在：{source}")
    standalone = standalone_category(source)
    inferred_original: Path | None = None
    if standalone:
        category_name, target_suffix = standalone
        identity, inferred_original = resolve_standalone_identity(source)
        target = source.parent / f"{identity}-{target_suffix}优化"
    else:
        category_name = ""
        target = source.parent / f"{source.name}-优化"
    if target.exists():
        raise FileExistsError(f"输出文件夹已存在，未覆盖：{target}")

    main_dir = source if category_name == "主图" else source / "主图"
    if category_name == "详情页":
        detail_dir = source
    else:
        detail_dir = source / "详情页"
        if not detail_dir.is_dir() and (source / "详情").is_dir():
            detail_dir = source / "详情"
    sku_dir = source if category_name == "SKU" else find_casefold_dir(source, "SKU")
    present = [
        main_dir.is_dir() and category_name in {"", "主图"},
        detail_dir.is_dir() and category_name in {"", "详情页"},
        sku_dir is not None and category_name in {"", "SKU"},
    ]
    if not any(present):
        raise ValueError("输入文件夹中没有主图、详情页或 SKU 文件夹")

    if partial_detail and complete_detail:
        raise ValueError("--partial-detail 与 --complete-detail 不能同时使用")

    nearby_original: Path | None = inferred_original
    if detail_dir.is_dir() and category_name in {"", "详情页"} and nearby_original is None:
        try:
            nearby_original = find_original_package(source)
        except FileNotFoundError:
            nearby_original = None
    if detail_dir.is_dir() and category_name in {"", "详情页"} and nearby_original and not partial_detail and not complete_detail:
        raise RuntimeError(
            "附近存在同款 -全平台 原包，必须先确认当前详情是完整详情还是局部改款切片；"
            "局部改款请使用 --partial-detail 和 --replacement-map，确认是完整详情后才可使用 --complete-detail。"
            "禁止直接重拼爱库存+蜂享家详情。"
        )

    resolved_original_detail: Path | None = None
    if partial_detail:
        if not detail_dir.is_dir():
            raise ValueError("局部改款模式需要详情页文件夹")
        if replacement_map is None:
            raise ValueError("局部改款模式缺少 --replacement-map 替换定位 JSON")
        selected_package = original_package.expanduser().resolve() if original_package else (nearby_original or find_original_package(source))
        if not selected_package.is_dir():
            raise FileNotFoundError(f"原款全平台文件夹不存在：{selected_package}")
        resolved_original_detail = find_original_aik_detail(selected_package)

    staging = source.parent / f".{target.name}.staging-{uuid.uuid4().hex}"
    summary = {"source": str(source), "output": str(target), "images": 0, "warnings": [], "failures": []}
    try:
        staging.mkdir(parents=False)
        jobs = []
        if main_dir.is_dir() and category_name in {"", "主图"}:
            main_output = staging if category_name == "主图" else staging / "主图"
            jobs.append(("主图", lambda: build_main(main_dir, main_output, summary)))
        if detail_dir.is_dir() and category_name in {"", "详情页"}:
            detail_output = staging if category_name == "详情页" else staging / "详情页"
            if partial_detail:
                assert resolved_original_detail is not None and replacement_map is not None
                jobs.append((
                    "详情页局部改款",
                    lambda: build_partial_detail(
                        source,
                        detail_dir,
                        detail_output,
                        resolved_original_detail,
                        replacement_map.expanduser().resolve(),
                        summary,
                    ),
                ))
            else:
                jobs.append(("详情页", lambda: build_detail(detail_dir, detail_output, summary)))
        if sku_dir is not None and category_name in {"", "SKU"}:
            sku_output = staging if category_name == "SKU" else staging / "SKU"
            jobs.append(("SKU", lambda: build_sku(sku_dir, sku_output, summary)))
        for name, job in jobs:
            try:
                job()
            except Exception as exc:
                summary["failures"].append(f"{name}：{exc}")
        staging.rename(target)
        summary["status"] = "部分完成" if summary["failures"] else "完成"
        return target, summary
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="优化商品图片数据包中的主图、详情页和 SKU")
    parser.add_argument("--source", required=True, help="商品图片数据包文件夹")
    parser.add_argument("--partial-detail", action="store_true", help="启用少量改款详情图替换完整爱库存+蜂享家详情")
    parser.add_argument("--complete-detail", action="store_true", help="已人工确认输入是完整详情，允许按普通规则生成爱库存+蜂享家详情")
    parser.add_argument("--original-package", default="", help="原款全平台文件夹；省略时自动在上下级和同级查找")
    parser.add_argument("--replacement-map", default="", help="Agent 确认的详情图替换定位 JSON")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        _, summary = optimize_package(
            Path(args.source),
            partial_detail=args.partial_detail,
            complete_detail=args.complete_detail,
            original_package=Path(args.original_package) if args.original_package else None,
            replacement_map=Path(args.replacement_map) if args.replacement_map else None,
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
