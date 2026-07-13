from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image, ImageDraw

from common.source_pack_validator import validate_source_pack
from main import run_single


def create_rgb(path: Path, size: tuple[int, int] = (16, 12)) -> None:
    """创建用于目录结构测试的普通图片。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (220, 220, 220)).save(path)


def create_transparent(path: Path, dirty: bool = False) -> None:
    """创建单主体透明图，并可选加入主体外脏点。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle((12, 8, 28, 32), fill=(180, 120, 90, 255))
    if dirty:
        image.putpixel((3, 36), (255, 255, 255, 8))
    image.save(path)


def create_standard_pack(root: Path, sku_name: str = "SKU", dirty: bool = False) -> None:
    """创建满足强制目录结构的最小测试数据包。"""
    create_rgb(root / "主图" / "800" / "1.jpg")
    create_rgb(root / "主图" / "750" / "1.jpg")
    create_rgb(root / sku_name / "800" / "颜色.jpg")
    create_rgb(root / "白底图" / "颜色.jpg")
    create_transparent(root / "透明图" / "颜色.png", dirty=dirty)
    create_rgb(root / "详情" / "静态" / "1.jpg")


class SourcePackValidatorTests(unittest.TestCase):
    """验证输入包结构门禁和透明图脏点检测。"""

    def test_lowercase_sku_is_accepted(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "数据包"
            create_standard_pack(root, sku_name="sku")

            result = validate_source_pack(root)

            self.assertTrue(result["通过"])
            self.assertEqual(result["识别目录"]["SKU"]["实际名称"], "sku")

    def test_misnamed_main_directories_are_rejected(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "数据包"
            create_standard_pack(root)
            (root / "主图" / "800").rename(root / "主图" / "800主图")
            (root / "主图" / "750").rename(root / "主图" / "750 1000主图")

            result = validate_source_pack(root)

            self.assertFalse(result["通过"])
            messages = [item["信息"] for item in result["问题"]]
            self.assertTrue(any("800主图" in message for message in messages))
            self.assertTrue(any("750 1000主图" in message for message in messages))
            self.assertIn("产品名称/", result["标准输入结构"])
            self.assertIn("└─ 数据包/", result["标准输入结构"])

    def test_transparent_debris_is_rejected(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "数据包"
            create_standard_pack(root, dirty=True)

            result = validate_source_pack(root)

            self.assertFalse(result["通过"])
            debris = next(item for item in result["问题"] if "独立残留像素" in item["信息"])
            self.assertEqual(debris["主体外独立区域数"], 1)
            self.assertEqual(debris["主体外像素数"], 1)

    def test_regular_image_dimensions_are_not_checked(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "数据包"
            create_standard_pack(root)

            result = validate_source_pack(root)

            self.assertTrue(result["通过"])

    def test_empty_required_directory_is_rejected(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "数据包"
            create_standard_pack(root)
            (root / "白底图" / "颜色.jpg").unlink()

            result = validate_source_pack(root)

            self.assertFalse(result["通过"])
            self.assertTrue(any("必需目录没有图片" in item["信息"] for item in result["问题"]))

    def test_main_flow_stops_before_creating_platform_output(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source = temp_root / "产品" / "数据包"
            create_standard_pack(source)
            (source / "主图" / "800").rename(source / "主图" / "800主图")
            output_root = temp_root / "输出"
            report_path = temp_root / "检测报告.json"

            code = run_single(
                source,
                temp_root / "模板",
                output_root,
                "all",
                report_path,
            )

            self.assertEqual(code, 2)
            self.assertFalse(output_root.exists())
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertFalse(report["输入包检测"]["通过"])
            self.assertTrue(report["失败项"])
            self.assertIn("标准输入结构", report["输入包检测"])
            self.assertIn("└─ 数据包/", report["输入包检测"]["标准输入结构"])


if __name__ == "__main__":
    unittest.main()
