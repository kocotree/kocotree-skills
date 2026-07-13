from __future__ import annotations

from dataclasses import dataclass

from PIL import Image


默认左侧安全余量比例 = 0.03
标签保护边缘像素 = 6
近白色阈值 = 247
近白色色差阈值 = 8
彩色色差阈值 = 35


class CardCropError(RuntimeError):
    """右侧商品卡片或彩色标签无法可靠识别。"""


@dataclass(frozen=True)
class CardCropPlan:
    """右侧商品卡片裁切计划。"""

    card_left: int
    card_right: int
    crop_left: int
    scan_y: int
    image_size: tuple[int, int]
    label_boxes: tuple[tuple[int, int, int, int], ...]

    @property
    def crop_box(self) -> tuple[int, int, int, int]:
        """返回纵向裁片在原图中的坐标。"""
        width, height = self.image_size
        return self.crop_left, 0, width, height

    @property
    def editable_boxes(self) -> tuple[tuple[int, int, int, int], ...]:
        """返回扣除标签轮廓保护边缘后的可编辑区域。"""
        boxes = []
        for left, top, right, bottom in self.label_boxes:
            inset = min(
                标签保护边缘像素,
                max(1, (right - left) // 6),
                max(1, (bottom - top) // 6),
            )
            boxes.append((left + inset, top + inset, right - inset, bottom - inset))
        return tuple(boxes)


def detect_right_card_plan(
    image: Image.Image,
    left_padding_ratio: float = 默认左侧安全余量比例,
) -> CardCropPlan:
    """识别右侧白色商品卡片、纵向裁片和彩色标签。

    功能说明：从右半区域扫描卡片顶部近白色横带，定位商品卡片左边缘，
    再向左增加安全余量，并识别卡片内横向铺开的彩色装饰标签。

    参数：
        image：原始 SKU 图片，用于识别卡片和标签。
        left_padding_ratio：卡片左边缘向左扩展的图片宽度比例。
    返回值：
        CardCropPlan，包含卡片范围、裁切范围、标签范围和原图尺寸。
    """
    rgb = image.convert("RGB")
    width, height = rgb.size
    if width < 100 or height < 100:
        raise CardCropError(f"图片尺寸过小，无法识别商品卡片：{width}x{height}")

    card_left, card_right, scan_y = _detect_white_card_band(rgb)
    padding = max(12, round(width * max(0.0, left_padding_ratio)))
    crop_left = max(0, card_left - padding)
    if width - crop_left < round(width * 0.20):
        raise CardCropError(f"右侧裁片宽度过小，拒绝处理：x={crop_left}–{width - 1}")

    label_boxes = _detect_colored_label_boxes(rgb, card_left, card_right)
    if not label_boxes:
        raise CardCropError("右侧商品卡片内未可靠识别到横向彩色标签")

    return CardCropPlan(
        card_left=card_left,
        card_right=card_right,
        crop_left=crop_left,
        scan_y=scan_y,
        image_size=rgb.size,
        label_boxes=tuple(label_boxes),
    )


def build_model_input(image: Image.Image, plan: CardCropPlan) -> Image.Image:
    """构建与原图同尺寸、仅保留右侧纵向裁片的模型输入图。

    参数：
        image：原始 SKU 图片。
        plan：右侧商品卡片裁切计划。
    返回值：
        与原图宽高一致的 RGB 图片，左侧为背景色，右侧为原始裁片。
    """
    rgb = image.convert("RGB")
    if rgb.size != plan.image_size:
        raise CardCropError(f"裁切计划尺寸与原图不一致：{plan.image_size} != {rgb.size}")
    background = rgb.getpixel((0, 0))
    canvas = Image.new("RGB", rgb.size, background)
    crop = rgb.crop(plan.crop_box)
    canvas.paste(crop, (plan.crop_left, 0))
    return canvas


def normalize_model_output(image: Image.Image, expected_size: tuple[int, int]) -> Image.Image:
    """校验模型输出宽高比并恢复到模型输入像素尺寸。

    参数：
        image：模型返回的图片。
        expected_size：模型输入图片的宽高。
    返回值：
        与模型输入宽高完全一致的 RGB 图片。
    """
    rgb = image.convert("RGB")
    expected_ratio = expected_size[0] / expected_size[1]
    actual_ratio = rgb.width / rgb.height
    if abs(expected_ratio - actual_ratio) > 0.01:
        raise CardCropError(
            f"模型输出宽高比发生变化：输入{expected_size[0]}x{expected_size[1]}，"
            f"输出{rgb.width}x{rgb.height}"
        )
    if rgb.size == expected_size:
        return rgb
    return rgb.resize(expected_size, Image.Resampling.LANCZOS)


def validate_protected_regions(
    original: Image.Image,
    generated: Image.Image,
    plan: CardCropPlan,
    max_mean_difference: float = 8.0,
    max_changed_ratio: float = 0.03,
) -> dict[str, float | bool]:
    """检查模型是否修改了标签文字区域以外的右侧裁片。

    参数：
        original：原始 SKU 图片。
        generated：已恢复到输入尺寸的模型结果。
        plan：右侧商品卡片裁切计划。
        max_mean_difference：受保护区域允许的平均通道差异上限。
        max_changed_ratio：受保护区域允许的明显变化像素比例上限。
    返回值：
        包含是否通过、平均差异和明显变化比例的验收结果。
    """
    original_rgb = original.convert("RGB")
    generated_rgb = generated.convert("RGB")
    if original_rgb.size != generated_rgb.size or original_rgb.size != plan.image_size:
        raise CardCropError("原图、模型输出和裁切计划的尺寸必须一致")

    editable_boxes = plan.editable_boxes
    source_pixels = original_rgb.load()
    output_pixels = generated_rgb.load()
    total_difference = 0
    compared_pixels = 0
    changed_pixels = 0
    width, height = plan.image_size

    for y in range(height):
        for x in range(plan.crop_left, width):
            if _inside_any_box(x, y, editable_boxes):
                continue
            source_pixel = source_pixels[x, y]
            output_pixel = output_pixels[x, y]
            differences = [abs(a - b) for a, b in zip(source_pixel, output_pixel)]
            total_difference += sum(differences)
            compared_pixels += 1
            if max(differences) > 25:
                changed_pixels += 1

    if compared_pixels == 0:
        raise CardCropError("没有可用于验收的受保护区域")
    mean_difference = total_difference / (compared_pixels * 3)
    changed_ratio = changed_pixels / compared_pixels
    passed = mean_difference <= max_mean_difference and changed_ratio <= max_changed_ratio
    return {
        "通过": passed,
        "平均通道差异": round(mean_difference, 4),
        "明显变化比例": round(changed_ratio, 6),
    }


def composite_editable_regions(
    original: Image.Image,
    generated: Image.Image,
    plan: CardCropPlan,
) -> Image.Image:
    """仅将标签内部可编辑区域贴回原图。

    参数：
        original：原始 SKU 图片，作为最终输出底图。
        generated：通过验收且已恢复尺寸的模型结果。
        plan：右侧商品卡片裁切计划。
    返回值：
        与原图尺寸一致、仅标签内部来自模型结果的 RGB 图片。
    """
    original_rgb = original.convert("RGB")
    generated_rgb = generated.convert("RGB")
    if original_rgb.size != generated_rgb.size or original_rgb.size != plan.image_size:
        raise CardCropError("拼接前原图、模型输出和裁切计划的尺寸必须一致")
    result = original_rgb.copy()
    for box in plan.editable_boxes:
        result.paste(generated_rgb.crop(box), (box[0], box[1]))
    return result


def _detect_white_card_band(image: Image.Image) -> tuple[int, int, int]:
    width, height = image.size
    candidates = []
    for y in range(round(height * 0.20), round(height * 0.45)):
        for left, right in _white_runs_at_row(image, y):
            run_width = right - left
            if (
                left >= round(width * 0.45)
                and right >= round(width * 0.85)
                and right <= round(width * 0.99)
                and run_width >= round(width * 0.20)
            ):
                candidates.append((run_width, left, right, y))
    if not candidates:
        raise CardCropError("未可靠识别到右侧商品卡片顶部白色横带")
    _, left, right, scan_y = max(candidates)
    return left, right, scan_y


def _white_runs_at_row(image: Image.Image, y: int) -> list[tuple[int, int]]:
    width, _ = image.size
    active = []
    for x in range(width // 2, width):
        red, green, blue = image.getpixel((x, y))
        if (
            min(red, green, blue) >= 近白色阈值
            and max(red, green, blue) - min(red, green, blue) <= 近白色色差阈值
        ):
            active.append(x)
    return _group_contiguous_values(active)


def _detect_colored_label_boxes(
    image: Image.Image,
    card_left: int,
    card_right: int,
) -> list[tuple[int, int, int, int]]:
    _, height = image.size
    card_width = card_right - card_left
    active_rows = []
    colored_by_row: dict[int, list[int]] = {}
    for y in range(round(height * 0.20), round(height * 0.85)):
        colored_x = []
        for x in range(card_left, card_right):
            red, green, blue = image.getpixel((x, y))
            if max(red, green, blue) - min(red, green, blue) >= 彩色色差阈值:
                colored_x.append(x)
        if len(colored_x) >= round(card_width * 0.55):
            active_rows.append(y)
            colored_by_row[y] = colored_x

    boxes = []
    for top, bottom_inclusive in _group_contiguous_values(active_rows, max_gap=2):
        bottom = bottom_inclusive + 1
        if bottom - top < max(12, round(height * 0.02)):
            continue
        xs = []
        for y in range(top, bottom):
            xs.extend(colored_by_row.get(y, []))
        if not xs:
            continue
        left = min(xs)
        right = max(xs) + 1
        if right - left < round(card_width * 0.60):
            continue
        boxes.append((left, top, right, bottom))
    return boxes


def _group_contiguous_values(values: list[int], max_gap: int = 1) -> list[tuple[int, int]]:
    if not values:
        return []
    groups = []
    start = previous = values[0]
    for value in values[1:]:
        if value <= previous + max_gap:
            previous = value
            continue
        groups.append((start, previous))
        start = previous = value
    groups.append((start, previous))
    return groups


def _inside_any_box(
    x: int,
    y: int,
    boxes: tuple[tuple[int, int, int, int], ...],
) -> bool:
    return any(left <= x < right and top <= y < bottom for left, top, right, bottom in boxes)
