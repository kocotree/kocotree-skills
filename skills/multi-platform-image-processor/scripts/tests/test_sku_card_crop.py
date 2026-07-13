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


def create_model_candidates(source: Path, output_dir: Path) -> tuple[Path, Path]:
    """根据实际保存后的测试原图创建验收失败和验收通过的模型候选图。"""
    original = Image.open(source).convert("RGB")
    plan = detect_right_card_plan(original)
    model_input = build_model_input(original, plan)

    bad_path = output_dir / "bad.png"
    bad_image = model_input.copy()
    ImageDraw.Draw(bad_image).rectangle(
        (plan.crop_left, 0, original.width - 1, round(original.height * 0.62)),
        fill=(220, 60, 55),
    )
    bad_image.save(bad_path)

    good_path = output_dir / "good.png"
    good_image = model_input.copy()
    editable_box = plan.editable_boxes[0]
    ImageDraw.Draw(good_image).rectangle(editable_box, fill=(42, 165, 78))
    good_image.save(good_path)
    return bad_path, good_path


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
        self.assertEqual(model_input.getpixel((100, 400)), (255, 255, 255))

    def test_validation_only_compares_right_crop(self) -> None:
        image = create_sample_sku()
        plan = detect_right_card_plan(image)
        model_input = build_model_input(image, plan)
        generated = model_input.copy()
        ImageDraw.Draw(generated).rectangle((0, 0, plan.crop_left - 1, 799), fill=(0, 0, 0))

        audit = validate_protected_regions(model_input, generated, plan)

        self.assertTrue(audit["通过"])
        self.assertEqual(audit["平均通道差异"], 0.0)
        self.assertEqual(audit["明显变化比例"], 0.0)
        self.assertEqual(audit["比较起始X"], plan.crop_left)

    def test_normalize_model_output_accepts_proportional_resolution(self) -> None:
        generated = create_sample_sku().resize((1600, 1600))
        normalized = normalize_model_output(generated, (800, 800))

        self.assertEqual(normalized.size, (800, 800))

    def test_validation_rejects_change_outside_label(self) -> None:
        image = create_sample_sku()
        plan = detect_right_card_plan(image)
        model_input = build_model_input(image, plan)
        generated = model_input.copy()
        draw = ImageDraw.Draw(generated)
        draw.rectangle((plan.crop_left, 0, 799, 500), fill=(220, 60, 55))

        audit = validate_protected_regions(model_input, generated, plan)

        self.assertFalse(audit["通过"])

    def test_composite_only_changes_label_interior(self) -> None:
        image = create_sample_sku()
        plan = detect_right_card_plan(image)
        model_input = build_model_input(image, plan)
        generated = model_input.copy()
        editable_box = plan.editable_boxes[0]
        ImageDraw.Draw(generated).rectangle(editable_box, fill=(42, 165, 78))

        audit = validate_protected_regions(model_input, generated, plan)
        result = composite_editable_regions(image, generated, plan)

        self.assertTrue(audit["通过"])
        self.assertEqual(result.size, image.size)
        self.assertEqual(result.getpixel((100, 100)), image.getpixel((100, 100)))
        self.assertNotEqual(
            result.crop(editable_box).tobytes(),
            image.crop(editable_box).tobytes(),
        )

    def test_validation_rejects_new_object_inside_label(self) -> None:
        image = create_sample_sku()
        plan = detect_right_card_plan(image)
        model_input = build_model_input(image, plan)
        generated = model_input.copy()
        left, top, right, bottom = plan.editable_boxes[0]
        ImageDraw.Draw(generated).rectangle(
            (right - (right - left) // 3, top, right - 1, bottom - 1),
            fill=(225, 175, 145),
        )

        audit = validate_protected_regions(model_input, generated, plan)

        self.assertFalse(audit["通过"])
        self.assertGreater(
            audit["标签内部非文字变化比例"],
            audit["标签内部非文字变化比例阈值"],
        )

    def test_process_retries_model_call_failure_and_can_succeed(self) -> None:
        with TemporaryDirectory() as temp_dir_value:
            temp_dir = Path(temp_dir_value)
            source = temp_dir / "source.jpg"
            output = temp_dir / "output.jpg"
            create_sample_sku().save(source, quality=95)
            _, good_generated = create_model_candidates(source, temp_dir)
            report = {"风险": [], "失败项": [], "警告": [], "图片记录": []}

            with patch(
                "common.text_removal.get_text_removal_temp_dir",
                return_value=temp_dir,
            ), patch(
                "common.text_removal._run_text_removal",
                side_effect=[
                    (None, "第一次模型调用失败"),
                    (good_generated, "第二次模型调用成功"),
                ],
            ) as run_mock:
                saved = process_offsite_sku_text_removal(
                    source,
                    output,
                    500 * 1024,
                    report,
                    "站外通用版",
                    cleanup_temp=False,
                )

            self.assertIsNotNone(saved)
            self.assertEqual(run_mock.call_count, 2)
            self.assertFalse(report["风险"])

    def test_process_retries_validation_failure_and_can_succeed(self) -> None:
        with TemporaryDirectory() as temp_dir_value:
            temp_dir = Path(temp_dir_value)
            source = temp_dir / "source.jpg"
            output = temp_dir / "output.jpg"
            create_sample_sku().save(source, quality=95)
            bad_generated, good_generated = create_model_candidates(source, temp_dir)
            report = {"风险": [], "失败项": [], "警告": [], "图片记录": []}

            with patch(
                "common.text_removal.get_text_removal_temp_dir",
                return_value=temp_dir,
            ), patch(
                "common.text_removal._run_text_removal",
                side_effect=[
                    (bad_generated, "第一次模型结果"),
                    (good_generated, "第二次模型结果"),
                ],
            ) as run_mock:
                saved = process_offsite_sku_text_removal(
                    source,
                    output,
                    500 * 1024,
                    report,
                    "站外通用版",
                    cleanup_temp=False,
                )

            self.assertIsNotNone(saved)
            self.assertEqual(run_mock.call_count, 2)
            self.assertFalse(report["风险"])

    def test_process_records_after_second_model_call_failure(self) -> None:
        with TemporaryDirectory() as temp_dir_value:
            temp_dir = Path(temp_dir_value)
            source = temp_dir / "source.jpg"
            output = temp_dir / "output.jpg"
            create_sample_sku().save(source, quality=95)
            report = {"风险": [], "失败项": [], "警告": [], "图片记录": []}

            with patch(
                "common.text_removal.get_text_removal_temp_dir",
                return_value=temp_dir,
            ), patch(
                "common.text_removal._run_text_removal",
                return_value=(None, "模型服务不可用"),
            ) as run_mock:
                saved = process_offsite_sku_text_removal(
                    source,
                    output,
                    500 * 1024,
                    report,
                    "站外通用版",
                    cleanup_temp=False,
                )

            self.assertIsNotNone(saved)
            self.assertEqual(run_mock.call_count, 2)
            self.assertEqual(len(report["风险"]), 1)
            self.assertEqual(report["风险"][0]["尝试次数"], 2)
            self.assertEqual(len(report["风险"][0]["原因"]), 2)

    def test_process_rejects_bad_model_result_and_outputs_original(self) -> None:
        with TemporaryDirectory() as temp_dir_value:
            temp_dir = Path(temp_dir_value)
            source = temp_dir / "source.jpg"
            output = temp_dir / "output.jpg"
            create_sample_sku().save(source, quality=95)
            bad_generated, _ = create_model_candidates(source, temp_dir)
            report = {"风险": [], "失败项": [], "警告": [], "图片记录": []}

            with patch(
                "common.text_removal.get_text_removal_temp_dir",
                return_value=temp_dir,
            ), patch(
                "common.text_removal._run_text_removal",
                return_value=(bad_generated, "测试模型结果"),
            ) as run_mock:
                saved = process_offsite_sku_text_removal(
                    source,
                    output,
                    500 * 1024,
                    report,
                    "站外通用版",
                    cleanup_temp=False,
                )

            self.assertIsNotNone(saved)
            self.assertEqual(run_mock.call_count, 2)
            self.assertEqual(len(report["风险"]), 1)
            self.assertEqual(report["风险"][0]["尝试次数"], 2)
            self.assertEqual(len(report["风险"][0]["原因"]), 2)
            saved_image = Image.open(saved).convert("RGB")
            red, green, blue = saved_image.getpixel((600, 60))
            self.assertLess(abs(red - green), 10)
            self.assertLess(abs(green - blue), 10)


if __name__ == "__main__":
    unittest.main()
