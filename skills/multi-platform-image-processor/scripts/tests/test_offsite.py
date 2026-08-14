from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from common import new_report
from platforms.offsite import derive


class OffsiteTests(unittest.TestCase):
    """验证站外平台素材图派生流程。"""

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
