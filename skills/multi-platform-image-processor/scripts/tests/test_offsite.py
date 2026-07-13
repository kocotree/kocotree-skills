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
            report = new_report(source_root, None, output_root, "offsite")

            platform_dir = derive(source_root, None, output_root, report)

            self.assertTrue((platform_dir / "素材图" / "子目录" / "图片.jpg").exists())
            self.assertFalse(report["失败项"])


if __name__ == "__main__":
    unittest.main()
