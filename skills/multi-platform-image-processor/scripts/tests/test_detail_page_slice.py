from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from common.detail_page_slice import prepare_ordered_detail_sources


def create_rgb(path: Path, size: tuple[int, int] = (16, 12)) -> None:
    """创建用于详情页测试的普通图片。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (220, 220, 220)).save(path)


class DetailPageSliceTests(unittest.TestCase):
    """验证详情页模块计划的排序与拆分。"""

    def test_detail_plan_reorders_required_modules_and_splits_joined_image(self) -> None:
        """验证详情计划按固定模块顺序输出并水平拆分连体图。"""
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "数据包"
            static = root / "详情" / "静态"
            for name in ("01.jpg", "04.jpg", "05.jpg", "06.jpg"):
                create_rgb(static / name, (790, 120))
            create_rgb(static / "02.jpg", (790, 200))
            plan_path = Path(temp_dir) / "detail-plan.json"
            plan_path.write_text(
                json.dumps(
                    {
                        "详情模块": [
                            {"类型": "尺码表", "图片": "详情/静态/05.jpg"},
                            {"类型": "图标说明", "图片": "详情/静态/02.jpg", "区域": [0, 100, 790, 200]},
                            {"类型": "品牌背书", "图片": "详情/静态/01.jpg"},
                            {"类型": "产品信息", "图片": "详情/静态/04.jpg"},
                            {"类型": "尺码快选", "图片": "详情/静态/06.jpg"},
                            {"类型": "KV", "图片": "详情/静态/02.jpg", "区域": [0, 0, 790, 100]},
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            report: dict = {}
            corrected = Path(temp_dir) / "修正版" / "04.jpg"
            create_rgb(corrected, (790, 120))

            outputs = prepare_ordered_detail_sources(
                root,
                plan_path,
                Path(temp_dir) / "staging",
                report,
                {(static / "04.jpg").resolve(): corrected},
            )

            self.assertEqual(
                [item["类型"] for item in report["详情页模块"]["模块顺序"]],
                ["品牌背书", "KV", "图标说明", "产品信息", "尺码表", "尺码快选"],
            )
            with Image.open(outputs[1]) as kv, Image.open(outputs[2]) as icon:
                self.assertEqual(kv.size, (790, 100))
                self.assertEqual(icon.size, (790, 100))
            self.assertEqual(outputs[3], corrected)
            self.assertTrue(report["详情页模块"]["模块顺序"][3]["面料已修正"])

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


if __name__ == "__main__":
    unittest.main()
