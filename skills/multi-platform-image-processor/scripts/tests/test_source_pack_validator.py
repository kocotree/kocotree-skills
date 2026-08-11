from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image

from common.detail_page_slice import collect_detail_sources, prepare_ordered_detail_sources
from common.source_pack_validator import validate_source_pack
from workflows.platform_processing import run_single


def create_rgb(path: Path, size: tuple[int, int] = (16, 12)) -> None:
    """创建用于目录结构测试的普通图片。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (220, 220, 220)).save(path)


def create_standard_pack(
    root: Path,
    sku_name: str = "SKU",
) -> None:
    """创建满足强制目录结构的最小测试数据包。"""
    create_rgb(root / "主图" / "800" / "1.jpg")
    create_rgb(root / "主图" / "750" / "1.jpg")
    create_rgb(root / sku_name / "800" / "颜色.jpg")
    create_rgb(root / "白底图" / "颜色.jpg")
    create_rgb(root / "透明图" / "颜色.png")
    create_rgb(root / "详情" / "静态" / "1.jpg")


class SourcePackValidatorTests(unittest.TestCase):
    """验证输入包目录结构门禁。"""

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

    def test_image_content_and_dimensions_are_not_checked(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "数据包"
            create_standard_pack(root)

            result = validate_source_pack(root)

            self.assertTrue(result["通过"])
            self.assertEqual(set(result), {"通过", "问题", "警告", "识别目录"})

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

    def test_detail_plan_reorders_required_modules_and_splits_joined_image(self) -> None:
        """验证详情计划按固定模块顺序输出并水平拆分连体图。"""
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "数据包"
            static = root / "详情" / "静态"
            for name in ("01.jpg", "02.jpg", "04.jpg", "05.jpg"):
                create_rgb(static / name, (790, 120))
            create_rgb(static / "03.jpg", (790, 200))
            plan_path = Path(temp_dir) / "detail-plan.json"
            plan_path.write_text(
                json.dumps(
                    {
                        "详情模块": [
                            {"类型": "尺码表", "图片": "详情/静态/05.jpg"},
                            {"类型": "图标说明", "图片": "详情/静态/03.jpg", "区域": [0, 100, 790, 200]},
                            {"类型": "品牌背书", "图片": "详情/静态/01.jpg"},
                            {"类型": "产品信息", "图片": "详情/静态/04.jpg"},
                            {"类型": "KV", "图片": "详情/静态/02.jpg"},
                            {"类型": "适用图标", "图片": "详情/静态/03.jpg", "区域": [0, 0, 790, 100]},
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            report: dict = {}

            outputs = prepare_ordered_detail_sources(root, plan_path, Path(temp_dir) / "staging", report)

            self.assertEqual(
                [item["类型"] for item in report["详情页模块"]["模块顺序"]],
                ["品牌背书", "KV", "适用图标", "产品信息", "尺码表", "图标说明"],
            )
            with Image.open(outputs[2]) as icon, Image.open(outputs[5]) as explanation:
                self.assertEqual(icon.size, (790, 100))
                self.assertEqual(explanation.size, (790, 100))

    def test_detail_plan_requires_every_business_module(self) -> None:
        """验证详情计划缺少必需模块时停止处理。"""
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "数据包"
            create_rgb(root / "详情" / "静态" / "01.jpg", (790, 120))
            plan_path = Path(temp_dir) / "detail-plan.json"
            plan_path.write_text(
                json.dumps(
                    {"详情模块": [{"类型": "KV", "图片": "详情/静态/01.jpg"}]},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(RuntimeError, "缺少必需模块"):
                prepare_ordered_detail_sources(root, plan_path, Path(temp_dir) / "staging", {})

    def test_main_flow_stops_before_creating_platform_output(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source = temp_root / "产品" / "数据包"
            create_standard_pack(source)
            (source / "主图" / "800").rename(source / "主图" / "800主图")
            output_root = temp_root / "输出"
            report_path = temp_root / "检测报告.json"

            with patch("workflows.platform_processing.default_report_path", return_value=report_path):
                code, _, _ = run_single(
                    source,
                    temp_root / "模板",
                    output_root,
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
