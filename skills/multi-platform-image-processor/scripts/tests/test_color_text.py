from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image, ImageChops, ImageDraw

from common.color_text import _clean_glyph_mask, prepare_color_overrides, rename_color_file, replace_color_glyphs
from common.utils import new_report
from platforms.fengxiang_aikucun import _copy_sku800_tree, derive


class ColorTextTests(unittest.TestCase):
    """验证颜色改字的原字形保留、平台隔离与文件命名。"""

    def test_filename_only_changes_color_word(self):
        """验证名称替换保留目录与后缀且不改无关的麋字。"""
        self.assertEqual(rename_color_file(Path("分支/800/麋鹿呦呦.jpg")), Path("分支/800/小鹿呦呦.jpg"))
        self.assertEqual(rename_color_file(Path("麋鹿款/麋色.png")), Path("麋鹿款/麋色.png"))

    def fixture(self, root):
        """创建同字号的原字与参考字，并提供原图定位项。"""
        source = root / "SKU/800/麋鹿呦呦.png"
        source.parent.mkdir(parents=True)
        image = Image.new("RGB", (100, 80), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((22, 22, 36, 36), fill="black")
        draw.rectangle((55, 22, 57, 36), fill="black")
        draw.rectangle((62, 25, 64, 33), fill="black")
        image.save(source)
        return source, {"图片": "SKU/800/麋鹿呦呦.png", "原文": "麋鹿呦呦",
                        "原字区域": [20, 20, 40, 40], "参考图片": "SKU/800/麋鹿呦呦.png",
                        "参考字区域": [50, 20, 70, 40]}

    def test_reference_glyph_replaces_only_target_cell(self):
        """验证字体像素直接复用，目标字框外及原始文件完全不变。"""
        with TemporaryDirectory() as temp:
            root = Path(temp)
            source, item = self.fixture(root)
            before = hashlib.sha256(source.read_bytes()).digest()
            output = replace_color_glyphs(source, root / "output.png", [item], root)
            with Image.open(source) as original, Image.open(output) as changed:
                self.assertEqual(changed.crop((20, 20, 40, 40)).tobytes(), original.crop((50, 20, 70, 40)).tobytes())
                difference = ImageChops.difference(original, changed)
                self.assertIsNotNone(difference.getbbox())
                ImageDraw.Draw(difference).rectangle((20, 20, 39, 39), fill="black")
                self.assertIsNone(difference.getbbox())
            self.assertEqual(hashlib.sha256(source.read_bytes()).digest(), before)

    def test_material_correction_is_kept_in_platform_override(self):
        """验证颜色修改保留此前的面料修正，原图和共享修正版不变。"""
        with TemporaryDirectory() as temp:
            root = Path(temp)
            source, item = self.fixture(root)
            corrected = root / "material.png"
            with Image.open(source) as opened:
                image = opened.copy()
            image.putpixel((90, 70), (1, 2, 3))
            image.save(corrected)
            overrides = prepare_color_overrides(root, [item], root / "staging", {source.resolve(): corrected})
            with Image.open(overrides[source.resolve()]) as output:
                self.assertEqual(output.getpixel((90, 70)), (1, 2, 3))
            with Image.open(corrected) as unchanged:
                self.assertEqual(unchanged.getpixel((25, 25)), (0, 0, 0))

    def test_sku_pipeline_uses_override_and_renames_file(self):
        """验证仅蜂享家 SKU 使用改字图，输出名称与新颜色一致。"""
        with TemporaryDirectory() as temp:
            root = Path(temp)
            source, item = self.fixture(root)
            overrides = prepare_color_overrides(root, [item], root / "staging")
            report = new_report(root, None, root / "output")
            with patch("platforms.fengxiang_aikucun.process_jpg_original_or_compress") as render:
                _copy_sku800_tree(root, root / "output", report, overrides)
            self.assertEqual(render.call_args.args[0], overrides[source.resolve()])
            self.assertEqual(render.call_args.args[1].name, "小鹿呦呦.jpg")
            self.assertTrue(source.is_file())

    def test_mismatched_reference_size_is_rejected(self):
        """验证参考字框大小不同不被自动缩放导致字号变化。"""
        with TemporaryDirectory() as temp:
            root = Path(temp)
            source, item = self.fixture(root)
            item["参考字区域"] = [50, 20, 71, 40]
            with self.assertRaisesRegex(ValueError, "同字号"):
                replace_color_glyphs(source, root / "output.png", [item], root)

    def test_reference_frame_excludes_adjacent_character_stroke(self):
        """验证同步调整两处字框后排除邻字残笔，字形位置保持不变。"""
        with TemporaryDirectory() as temp:
            root = Path(temp)
            source, item = self.fixture(root)
            with Image.open(source) as opened:
                image = opened.copy()
            image.putpixel((69, 25), (0, 0, 0))
            image.save(source)
            item["原字区域"] = [18, 20, 38, 40]
            item["参考字区域"] = [48, 20, 68, 40]
            output = replace_color_glyphs(source, root / "output.png", [item], root)
            with Image.open(output) as changed:
                self.assertEqual(changed.getpixel((39, 25)), (255, 255, 255))
                self.assertEqual(changed.getpixel((25, 25)), (0, 0, 0))

    def test_empty_plan_keeps_shared_overrides(self):
        """验证没有命中词时只透传现有材质修正映射。"""
        original = {Path("source"): Path("material")}
        self.assertEqual(prepare_color_overrides(Path("root"), [], Path("staging"), original), original)

    def test_mask_keeps_separate_strokes_and_antialiasing(self):
        """验证多个独立笔画和原透明度保留，邻字碎片被清除。"""
        mask = Image.new("L", (50, 50))
        draw = ImageDraw.Draw(mask)
        draw.rectangle((20, 5, 24, 40), fill=255)
        draw.rectangle((5, 15, 8, 30), fill=180)
        draw.rectangle((35, 15, 38, 30), fill=200)
        mask.putpixel((19, 10), 25)
        expected = mask.copy()
        draw.rectangle((48, 25, 48, 29), fill=160)
        mask.putpixel((49, 27), 20)
        cleaned = _clean_glyph_mask(mask)
        self.assertEqual(cleaned.tobytes(), expected.tobytes())
        self.assertEqual(mask.getpixel((48, 25)), 160)

    def test_pipeline_removes_fragment_inside_reference_box(self):
        """验证实际改字流程清除框内邻字碎片并保留各笔画。"""
        with TemporaryDirectory() as temp:
            root = Path(temp)
            source, item = self.fixture(root)
            with Image.open(source) as opened:
                image = opened.copy()
            expected = image.crop(tuple(item["参考字区域"]))
            image.putpixel((69, 25), (0, 0, 0))
            image.save(source)
            output = replace_color_glyphs(source, root / "output.png", [item], root)
            with Image.open(output) as changed:
                self.assertEqual(changed.crop(tuple(item["原字区域"])).tobytes(), expected.tobytes())

    def test_detail_edit_happens_before_platform_slicing(self):
        """验证详情实际派生使用颜色修正版且共享天猫图不变。"""
        with TemporaryDirectory() as temp:
            root = Path(temp)
            reference, item = self.fixture(root)
            detail = root / "详情/source.png"
            detail.parent.mkdir()
            detail.write_bytes(reference.read_bytes())
            item["图片"] = "详情/source.png"
            plan = root / "detail-plan.json"
            plan.write_text(json.dumps({"详情模块": [{"图片": "详情/source.png", "类型": "产品信息"}]}), encoding="utf-8")
            shared = root / "天猫/790详情页/601.jpg"
            shared.parent.mkdir(parents=True)
            with Image.open(detail) as image:
                image.save(shared)
            before = shared.read_bytes()
            report = new_report(root, None, root / "output")
            output = derive(root, root / "天猫", root / "output", report, {}, [item], plan)
            with Image.open(output / "790详情页/详情图-01.jpg") as image:
                self.assertGreater(min(image.getpixel((174, 174))), 220)
            self.assertEqual(shared.read_bytes(), before)
            self.assertFalse(report["失败项"])
