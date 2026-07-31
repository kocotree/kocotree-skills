from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image, ImageDraw

from common.detail_page_slice import collect_detail_sources
from common.source_pack_validator import validate_source_pack
from main import run_single


def create_rgb(path: Path, size: tuple[int, int] = (16, 12)) -> None:
    """创建用于目录结构测试的普通图片。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (220, 220, 220)).save(path)


def create_transparent(
    path: Path,
    dirty: bool = False,
    second_subject: bool = False,
    uncertain: bool = False,
    faint: bool = False,
) -> None:
    """创建透明图，并按需加入第二主体、待确认区域或脏点。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle((12, 8, 28, 32), fill=(180, 120, 90, 255))
    if second_subject:
        ImageDraw.Draw(image).rectangle((2, 12, 8, 28), fill=(110, 150, 210, 255))
    if uncertain:
        ImageDraw.Draw(image).rectangle((3, 3, 4, 5), fill=(120, 160, 210, 255))
    if dirty:
        image.putpixel((3, 36), (255, 255, 255, 255))
    if faint:
        image.putpixel((36, 3), (255, 255, 255, 8))
    image.save(path)


def create_standard_pack(
    root: Path,
    sku_name: str = "SKU",
    dirty: bool = False,
    second_subject: bool = False,
    uncertain: bool = False,
    faint: bool = False,
) -> None:
    """创建满足强制目录结构的最小测试数据包。"""
    create_rgb(root / "主图" / "800" / "1.jpg")
    create_rgb(root / "主图" / "750" / "1.jpg")
    create_rgb(root / sku_name / "800" / "颜色.jpg")
    create_rgb(root / "白底图" / "颜色.jpg")
    create_transparent(
        root / "透明图" / "颜色.png",
        dirty=dirty,
        second_subject=second_subject,
        uncertain=uncertain,
        faint=faint,
    )
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
            temp_root = Path(temp_dir)
            root = temp_root / "数据包"
            visualization_dir = temp_root / "诊断图"
            create_standard_pack(root, dirty=True)

            result = validate_source_pack(root, visualization_dir)

            self.assertFalse(result["通过"])
            debris = next(item for item in result["问题"] if "独立残留像素" in item["信息"])
            self.assertEqual(debris["主体外独立区域数"], 1)
            self.assertEqual(debris["主体外像素数"], 1)
            self.assertTrue(Path(debris["可视化诊断图"]).exists())
            self.assertTrue(Path(result["透明图问题汇总"]).exists())
            with Image.open(debris["可视化诊断图"]) as diagnostic:
                self.assertGreater(diagnostic.height, 40)
                self.assertEqual(diagnostic.mode, "RGB")

    def test_multi_part_transparent_image_is_accepted(self) -> None:
        """验证两个明显主体组成部分可以通过检测。"""
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "数据包"
            create_standard_pack(root, second_subject=True)

            result = validate_source_pack(root)

            self.assertTrue(result["通过"])
            warning = next(
                item for item in result["警告"]
                if "多个主体组成部分" in item["信息"]
            )
            self.assertEqual(warning["主体区域数"], 2)
            self.assertEqual(warning["判定方式"], "自动判断")

    def test_uncertain_transparent_region_requires_confirmation(self) -> None:
        """验证大小不明确的独立区域需要文件规则确认。"""
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "数据包"
            create_standard_pack(root, uncertain=True)

            result = validate_source_pack(root)

            self.assertFalse(result["通过"])
            problem = next(
                item for item in result["问题"]
                if "无法自动判断" in item["信息"]
            )
            self.assertEqual(problem["待确认区域数"], 1)
            self.assertIn("透明图规则.json", problem["处理建议"])

    def test_component_rule_accepts_confirmed_second_subject(self) -> None:
        """验证文件规则可以确认较小的第二主体。"""
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "数据包"
            create_standard_pack(root, uncertain=True)
            rule_path = root / "透明图" / "透明图规则.json"
            rule_path.write_text(
                json.dumps(
                    {"文件规则": {"颜色.png": {"允许主体数": 2}}},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = validate_source_pack(root)

            self.assertTrue(result["通过"])
            warning = next(
                item for item in result["警告"]
                if "多个主体组成部分" in item["信息"]
            )
            self.assertEqual(warning["判定方式"], "文件规则")

    def test_component_rule_rejects_regions_over_limit(self) -> None:
        """验证文件规则之外的额外独立区域仍会阻断处理。"""
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "数据包"
            create_standard_pack(root, dirty=True, uncertain=True)
            rule_path = root / "透明图" / "透明图规则.json"
            rule_path.write_text(
                json.dumps(
                    {"文件规则": {"颜色.png": {"允许主体数": 2}}},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = validate_source_pack(root)

            self.assertFalse(result["通过"])
            problem = next(
                item for item in result["问题"]
                if "超过配置允许主体数" in item["信息"]
            )
            self.assertEqual(problem["主体外独立区域数"], 1)

    def test_nearly_transparent_single_pixel_is_ignored(self) -> None:
        """验证透明度不超过处理阈值的单像素不会形成独立区域。"""
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "数据包"
            create_standard_pack(root, faint=True)

            result = validate_source_pack(root)

            self.assertTrue(result["通过"])

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

    def test_flat_detail_mode_is_accepted_and_collected(self) -> None:
        """验证平铺详情结构通过检测并完整收集直接图片。"""
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "数据包"
            create_standard_pack(root)
            create_rgb(root / "详情" / "静态" / "2.jpg")

            result = validate_source_pack(root)
            sources = collect_detail_sources(root)

            self.assertTrue(result["通过"])
            self.assertEqual(result["识别目录"]["详情静态"]["模式"], "平铺")
            self.assertEqual([path.name for path in sources], ["1.jpg", "2.jpg"])

    def test_complete_upper_lower_detail_mode_is_accepted_and_ordered(self) -> None:
        """验证完整上/下详情结构通过检测并保持先上后下顺序。"""
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "数据包"
            create_standard_pack(root)
            (root / "详情" / "静态" / "1.jpg").unlink()
            create_rgb(root / "详情" / "静态" / "上" / "上-1.jpg")
            create_rgb(root / "详情" / "静态" / "下" / "下-1.jpg")

            result = validate_source_pack(root)
            sources = collect_detail_sources(root)

            self.assertTrue(result["通过"])
            self.assertEqual(result["识别目录"]["详情静态"]["模式"], "上/下")
            self.assertEqual([path.name for path in sources], ["上-1.jpg", "下-1.jpg"])

    def test_mixed_detail_mode_is_rejected(self) -> None:
        """验证平铺图片与上/下目录混用时立即失败。"""
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "数据包"
            create_standard_pack(root)
            create_rgb(root / "详情" / "静态" / "上" / "上-1.jpg")

            result = validate_source_pack(root)

            self.assertFalse(result["通过"])
            self.assertEqual(result["识别目录"]["详情静态"]["模式"], "混合结构")
            self.assertTrue(any("详情页结构混用" in item["信息"] for item in result["问题"]))
            with self.assertRaisesRegex(ValueError, "平铺图片不能与上/下目录同时存在"):
                collect_detail_sources(root)

    def test_upper_lower_detail_mode_requires_both_non_empty(self) -> None:
        """验证上/下模式的两个目录必须同时存在且分别包含图片。"""
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "数据包"
            create_standard_pack(root)
            (root / "详情" / "静态" / "1.jpg").unlink()
            create_rgb(root / "详情" / "静态" / "上" / "上-1.jpg")
            (root / "详情" / "静态" / "下").mkdir(parents=True)

            result = validate_source_pack(root)

            self.assertFalse(result["通过"])
            self.assertEqual(result["识别目录"]["详情静态"]["模式"], "上/下结构不完整")
            self.assertTrue(
                any("上/下目录必须分别包含图片" in item["信息"] for item in result["问题"])
            )

    def test_main_flow_stops_before_creating_platform_output(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source = temp_root / "产品" / "数据包"
            create_standard_pack(source)
            (source / "主图" / "800").rename(source / "主图" / "800主图")
            output_root = temp_root / "输出"
            report_path = temp_root / "检测报告.json"

            with patch("main.default_report_path", return_value=report_path):
                code = run_single(
                    source,
                    temp_root / "模板",
                    output_root,
                    "all",
                )

            self.assertEqual(code, 2)
            self.assertFalse(output_root.exists())
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertFalse(report["输入包检测"]["通过"])
            self.assertTrue(report["失败项"])
            self.assertNotIn("图片记录", report)
            self.assertEqual(report["图片统计"]["总数"], 0)
            self.assertTrue(Path(report["追溯文件"]["运行日志"]).exists())
            self.assertTrue(Path(report["追溯文件"]["逐图明细"]).exists())
            self.assertIn("标准输入结构", report["输入包检测"])
            self.assertIn("└─ 数据包/", report["输入包检测"]["标准输入结构"])


if __name__ == "__main__":
    unittest.main()
