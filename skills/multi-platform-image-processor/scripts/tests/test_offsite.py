from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from common import new_report
from common.quality_audit import audit_gift_sku_outputs
from platforms.fengxiang_aikucun import _copy_sku800_tree
from platforms.offsite import _select_offsite_sku_sources, _sku_output_path, derive
from platforms.tmall import _copy_sku_tree


class OffsiteTests(unittest.TestCase):
    """验证站外平台素材图派生流程。"""

    def test_sku_output_name_uses_only_specification(self) -> None:
        """验证站外 SKU 文件名不包含赠品与尺寸目录名称。"""
        source = Path("SKU") / "无赠品" / "800" / "企鹅团团-浅灰.jpg"
        output_dir = Path("输出") / "站外通用版" / "sku"

        output = _sku_output_path(source, Path("SKU"), output_dir, set())

        self.assertEqual(output, output_dir / "企鹅团团-浅灰.jpg")

    def test_nested_material_image_is_generated(self) -> None:
        with TemporaryDirectory() as temp_dir_value:
            temp_dir = Path(temp_dir_value)
            source_root = temp_dir / "数据包"
            material = source_root / "素材图" / "子目录" / "图片.jpg"
            material.parent.mkdir(parents=True)
            Image.new("RGB", (80, 60), (210, 220, 230)).save(material)
            output_root = temp_dir / "输出"
            report = new_report(source_root, None, output_root)

            platform_dir = derive(source_root, None, output_root, report, {})

            self.assertTrue((platform_dir / "素材图" / "子目录" / "图片.jpg").exists())
            self.assertTrue((platform_dir / "详情页").is_dir())
            self.assertTrue((platform_dir / "sku").is_dir())
            self.assertTrue((platform_dir / "白底图").is_dir())
            self.assertTrue((platform_dir / "白底图＋logo").is_dir())
            self.assertTrue((platform_dir / "透明图").is_dir())
            self.assertTrue((platform_dir / "主图").is_dir())
            self.assertFalse(report["失败项"])

    def test_gift_split_uses_only_no_gift_sku(self) -> None:
        """验证站外通用版只选择无赠品分支的 SKU 800 图。"""
        with TemporaryDirectory() as temp_dir_value:
            source_root = Path(temp_dir_value) / "数据包"
            gift = source_root / "SKU" / "加赠品" / "800" / "红色.jpg"
            no_gift = source_root / "SKU" / "无赠品" / "800" / "蓝色.jpg"
            no_gift_large = source_root / "SKU" / "无赠品" / "1400" / "蓝色.jpg"
            gift.parent.mkdir(parents=True)
            no_gift.parent.mkdir(parents=True)
            no_gift_large.parent.mkdir(parents=True)
            Image.new("RGB", (800, 800), "white").save(gift)
            Image.new("RGB", (800, 800), "white").save(no_gift)
            Image.new("RGB", (1400, 1400), "white").save(no_gift_large)

            selected = _select_offsite_sku_sources(source_root)

            self.assertEqual(selected, [no_gift.resolve()])

    def test_other_platforms_keep_gift_sku_paths(self) -> None:
        """验证天猫和蜂享家爱库存保留赠品与无赠品 SKU 分支。"""
        with TemporaryDirectory() as temp_dir_value:
            root = Path(temp_dir_value)
            source_root = root / "数据包"
            gift_800 = source_root / "SKU" / "加赠品" / "800" / "红色.jpg"
            gift_1440 = source_root / "SKU" / "加赠品" / "1440" / "红色.jpg"
            no_gift_800 = source_root / "SKU" / "无赠品" / "800" / "红色.jpg"
            no_gift_1400 = source_root / "SKU" / "无赠品" / "1400" / "红色.jpg"
            for source, size in (
                (gift_800, 800),
                (gift_1440, 1440),
                (no_gift_800, 800),
                (no_gift_1400, 1400),
            ):
                source.parent.mkdir(parents=True, exist_ok=True)
                Image.new("RGB", (size, size), "white").save(source)
            report = new_report(source_root, None, root / "输出")
            (root / "天猫sku" / "800").mkdir(parents=True)
            (root / "天猫sku" / "1440").mkdir(parents=True)

            _copy_sku_tree(source_root, root / "天猫sku", report)
            _copy_sku800_tree(source_root, root / "蜂享家sku", report)

            self.assertTrue((root / "天猫sku" / "加赠品" / "800" / "红色.jpg").is_file())
            self.assertTrue((root / "天猫sku" / "加赠品" / "1440" / "红色.jpg").is_file())
            self.assertTrue((root / "天猫sku" / "无赠品" / "800" / "红色.jpg").is_file())
            self.assertTrue((root / "天猫sku" / "无赠品" / "1400" / "红色.jpg").is_file())
            self.assertFalse((root / "天猫sku" / "800").exists())
            self.assertFalse((root / "天猫sku" / "1440").exists())
            self.assertTrue((root / "蜂享家sku" / "加赠品" / "800" / "红色.jpg").is_file())
            self.assertTrue((root / "蜂享家sku" / "无赠品" / "800" / "红色.jpg").is_file())
            self.assertFalse((root / "蜂享家sku" / "加赠品" / "1440" / "红色.jpg").exists())

    def test_gift_split_without_no_gift_800_fails(self) -> None:
        """验证赠品结构缺少无赠品 800 图时站外流程不会回退。"""
        with TemporaryDirectory() as temp_dir_value:
            source_root = Path(temp_dir_value) / "数据包"
            gift = source_root / "SKU" / "加赠品" / "800" / "红色.jpg"
            gift.parent.mkdir(parents=True)
            Image.new("RGB", (800, 800), "white").save(gift)

            with self.assertRaisesRegex(RuntimeError, "缺少无赠品分支"):
                _select_offsite_sku_sources(source_root)

    def test_gift_sku_output_audit_accepts_exact_branches(self) -> None:
        """验证赠品 SKU 输出按源相对目录通过质检。"""
        with TemporaryDirectory() as temp_dir_value:
            root = Path(temp_dir_value)
            source_root = root / "数据包"
            gift = source_root / "SKU" / "加赠品" / "800" / "红色.jpg"
            no_gift = source_root / "SKU" / "无赠品" / "800" / "红色.jpg"
            for source in (gift, no_gift):
                source.parent.mkdir(parents=True, exist_ok=True)
                Image.new("RGB", (800, 800), "white").save(source)
            report = new_report(source_root, None, root / "输出")
            tmall = root / "天猫"
            fengxiang = root / "蜂享家"
            _copy_sku_tree(source_root, tmall / "sku", report)
            _copy_sku800_tree(source_root, fengxiang / "800sku", report)

            audit_gift_sku_outputs(
                source_root,
                {"tmall": tmall, "fengxiang-aikucun": fengxiang},
                report,
            )

            self.assertFalse(report["失败项"])

    def test_regular_sku_structure_keeps_all_images(self) -> None:
        """验证没有赠品分支时站外通用版继续处理全部 SKU 800 图。"""
        with TemporaryDirectory() as temp_dir_value:
            root = Path(temp_dir_value)
            source_root = root / "数据包"
            sku = source_root / "SKU" / "800" / "蓝色.jpg"
            sku.parent.mkdir(parents=True)
            Image.new("RGB", (800, 800), "white").save(sku)
            report = new_report(source_root, None, root / "输出")

            selected = _select_offsite_sku_sources(source_root)
            _copy_sku_tree(source_root, root / "天猫sku", report)

            self.assertEqual(selected, [sku.resolve()])
            self.assertTrue((root / "天猫sku" / "800" / "蓝色.jpg").is_file())
            self.assertTrue((root / "天猫sku" / "1440").is_dir())

    def test_color_assets_use_sku_names(self) -> None:
        """验证站外白底图、Logo 图和透明图使用 SKU 颜色名称。"""
        with TemporaryDirectory() as temp_dir_value:
            temp_dir = Path(temp_dir_value)
            source_root = temp_dir / "数据包"
            white = source_root / "白底图" / "1.jpg"
            transparent = source_root / "透明图" / "1.png"
            white.parent.mkdir(parents=True)
            transparent.parent.mkdir(parents=True)
            Image.new("RGB", (80, 80), "white").save(white)
            Image.new("RGBA", (80, 80), (120, 80, 160, 255)).save(transparent)
            template = temp_dir / "模板"
            template.mkdir()
            Image.new("RGBA", (20, 20), (0, 160, 80, 255)).save(template / "logo3.png")
            output_root = temp_dir / "输出"
            report = new_report(source_root, template, output_root)
            color_names = {
                white.resolve(): "豆蔻紫",
                transparent.resolve(): "豆蔻紫",
            }

            platform_dir = derive(source_root, template, output_root, report, color_names)

            self.assertTrue((platform_dir / "白底图" / "豆蔻紫.jpg").is_file())
            self.assertTrue((platform_dir / "白底图＋logo" / "豆蔻紫.jpg").is_file())
            self.assertTrue((platform_dir / "透明图" / "豆蔻紫.png").is_file())
            self.assertFalse(report["失败项"])


if __name__ == "__main__":
    unittest.main()
