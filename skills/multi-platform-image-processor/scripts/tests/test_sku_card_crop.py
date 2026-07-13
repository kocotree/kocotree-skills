from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image, ImageDraw

from common.sku_card_crop import (
    build_model_input,
    composite_editable_regions,
    detect_right_card_plan,
    normalize_model_output,
    validate_protected_regions,
)
from common.text_removal import process_offsite_sku_text_removal


def create_sample_sku() -> Image.Image:
    """创建包含右侧白色卡片和彩色标签的通用测试图。"""
    image = Image.new("RGB", (800, 800), (238, 238, 238))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((510, 230, 770, 620), radius=14, fill=(255, 255, 255))
    draw.rectangle((590, 310, 700, 500), fill=(245, 210, 215))
    draw.rounded_rectangle((510, 520, 770, 620), radius=12, fill=(42, 165, 78))
    draw.rectangle((610, 555, 670, 585), fill=(255, 255, 255))
    return image


class SkuCardCropTests(unittest.TestCase):
    """验证站外 SKU 右侧裁片定位、尺寸约束和受保护区域验收。"""

    def test_detect_plan_includes_left_padding(self) -> None:
        image = create_sample_sku()
        plan = detect_right_card_plan(image)

        self.assertEqual(plan.card_left, 510)
        self.assertEqual(plan.crop_left, 486)
        self.assertEqual(plan.card_left - plan.crop_left, 24)
        self.assertEqual(plan.image_size, image.size)
        self.assertTrue(plan.label_boxes)

    def test_model_input_keeps_original_dimensions(self) -> None:
        image = create_sample_sku()
        plan = detect_right_card_plan(image)
        model_input = build_model_input(image, plan)

        self.assertEqual(model_input.size, image.size)
        self.assertEqual(
            model_input.crop(plan.crop_box).tobytes(),
            image.crop(plan.crop_box).tobytes(),
        )
        self.assertEqual(model_input.getpixel((100, 400)), image.getpixel((0, 0)))

    def test_normalize_model_output_accepts_proportional_resolution(self) -> None:
        generated = create_sample_sku().resize((1600, 1600))
        normalized = normalize_model_output(generated, (800, 800))

        self.assertEqual(normalized.size, (800, 800))

    def test_validation_rejects_change_outside_label(self) -> None:
        image = create_sample_sku()
        plan = detect_right_card_plan(image)
        generated = image.copy()
        draw = ImageDraw.Draw(generated)
        draw.rounded_rectangle((520, 20, 750, 100), radius=18, fill=(220, 60, 55))

        audit = validate_protected_regions(image, generated, plan)

        self.assertFalse(audit["通过"])

    def test_composite_only_changes_label_interior(self) -> None:
        image = create_sample_sku()
        plan = detect_right_card_plan(image)
        generated = image.copy()
        editable_box = plan.editable_boxes[0]
        ImageDraw.Draw(generated).rectangle(editable_box, fill=(42, 165, 78))

        audit = validate_protected_regions(image, generated, plan)
        result = composite_editable_regions(image, generated, plan)

        self.assertTrue(audit["通过"])
        self.assertEqual(result.size, image.size)
        self.assertEqual(result.getpixel((100, 100)), image.getpixel((100, 100)))
        self.assertNotEqual(
            result.crop(editable_box).tobytes(),
            image.crop(editable_box).tobytes(),
        )

    def test_process_rejects_bad_model_result_and_outputs_original(self) -> None:
        with TemporaryDirectory() as temp_dir_value:
            temp_dir = Path(temp_dir_value)
            source = temp_dir / "source.jpg"
            output = temp_dir / "output.jpg"
            bad_generated = temp_dir / "bad.png"
            create_sample_sku().save(source, quality=95)
            bad_image = create_sample_sku()
            ImageDraw.Draw(bad_image).rounded_rectangle(
                (520, 20, 750, 100),
                radius=18,
                fill=(220, 60, 55),
            )
            bad_image.save(bad_generated)
            report = {"风险": [], "失败项": [], "警告": [], "图片记录": []}

            with patch(
                "common.text_removal.get_text_removal_temp_dir",
                return_value=temp_dir,
            ), patch(
                "common.text_removal._run_text_removal",
                return_value=(bad_generated, "测试模型结果"),
            ):
                saved = process_offsite_sku_text_removal(
                    source,
                    output,
                    500 * 1024,
                    report,
                    "站外通用版",
                    cleanup_temp=False,
                )

            self.assertIsNotNone(saved)
            self.assertTrue(report["风险"])
            saved_image = Image.open(saved).convert("RGB")
            red, green, blue = saved_image.getpixel((600, 60))
            self.assertLess(abs(red - green), 10)
            self.assertLess(abs(green - blue), 10)


if __name__ == "__main__":
    unittest.main()
