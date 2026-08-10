from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from openpyxl import Workbook
import xlwt

from common.font_assets import load_font_assets, require_glyphs
from common.nas_paths import require_accessible_directory, to_unc_path
from common.product_info_reader import find_product_info, read_product_records
from common.product_matcher import select_representative_size, select_unique
from common.settings import resolve_business_paths
from common.source_normalizer import create_local_copy, create_modified_copy, detect_source_kind


class BusinessSettingsTests(unittest.TestCase):
    """验证业务路径配置和 UNC 路径归一化。"""

    def test_command_line_path_has_highest_priority(self) -> None:
        """验证命令行路径覆盖环境变量和配置文件。"""
        with TemporaryDirectory() as temp_dir_value:
            config = Path(temp_dir_value) / "paths.json"
            config.write_text(
                json.dumps(
                    {
                        "NAS根目录": r"\\config\share",
                        "产品信息相对目录": r"产品中心\产品信息",
                        "合格证相对目录": r"产品中心\合格证",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"KOCOTREE_NAS_ROOT": r"\\env\share"}):
                paths = resolve_business_paths(r"\\cli\share", config_path=config)

            self.assertEqual(str(paths.nas_root).rstrip("\\"), r"\\cli\share")
            self.assertIn("产品信息", str(paths.product_info_root))

    def test_drive_path_is_converted_to_unc(self) -> None:
        """验证映射盘路径转换为同一共享目录的 UNC 路径。"""
        converted = to_unc_path(
            r"Z:\产品中心\产品信息",
            {"Z:": r"\\192.168.110.20\浙江酷趣"},
        )

        self.assertEqual(
            str(converted),
            r"\\192.168.110.20\浙江酷趣\产品中心\产品信息",
        )

    def test_inaccessible_directory_reports_label(self) -> None:
        """验证不可访问目录返回带业务名称的错误。"""
        with TemporaryDirectory() as temp_dir_value:
            missing = Path(temp_dir_value) / "不存在"
            with self.assertRaisesRegex(RuntimeError, "产品信息目录不可访问"):
                require_accessible_directory(missing, "产品信息目录")


class ProductInfoTests(unittest.TestCase):
    """验证三种 Excel 格式读取和产品唯一匹配。"""

    @staticmethod
    def _write_openxml(path: Path) -> None:
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "产品资料"
        sheet.append(["说明"])
        sheet.append(["产品货号", "产品名称", "中文面料信息", "颜色", "尺码"])
        sheet.append(["KQ26143", "儿童长裤", "棉 95% 氨纶 5%", "蓝色", "110"])
        workbook.save(path)

    @staticmethod
    def _write_xls(path: Path) -> None:
        workbook = xlwt.Workbook()
        sheet = workbook.add_sheet("产品资料")
        values = [
            ["产品货号", "产品名称", "中文面料", "颜色", "尺码"],
            ["KQ25143", "儿童外套", "聚酯纤维 100%", "红色", "110"],
        ]
        for row_index, row in enumerate(values):
            for column_index, value in enumerate(row):
                sheet.write(row_index, column_index, value)
        workbook.save(str(path))

    def test_reads_xlsx_xlsm_and_xls(self) -> None:
        """验证三种产品信息文件均可读取中文面料。"""
        with TemporaryDirectory() as temp_dir_value:
            root = Path(temp_dir_value)
            xlsx = root / "KQ26143.xlsx"
            xlsm = root / "KQ26143.xlsm"
            xls = root / "KQ25143.xls"
            self._write_openxml(xlsx)
            self._write_openxml(xlsm)
            self._write_xls(xls)

            for path in (xlsx, xlsm, xls):
                records = read_product_records(path)
                self.assertEqual(len(records), 1)
                self.assertTrue(records[0].get("中文面料"))

    def test_multiple_excel_records_block_automatic_selection(self) -> None:
        """验证同货号存在多份产品信息时不自动猜测。"""
        with TemporaryDirectory() as temp_dir_value:
            root = Path(temp_dir_value)
            self._write_openxml(root / "KQ26143-A.xlsx")
            self._write_openxml(root / "KQ26143-B.xlsx")

            result = find_product_info(root, "KQ26143", "儿童长裤")

            self.assertIsNone(result.selected)
            self.assertEqual(len(result.candidates), 2)
            self.assertIn("多个", result.reason)


class ProductMatcherTests(unittest.TestCase):
    """验证货号边界和代表尺码选择。"""

    def test_product_code_requires_exact_boundary(self) -> None:
        """验证相邻的更长货号不会被当作精确匹配。"""
        result = select_unique(
            ["KQ26143 产品", "KQ261430 产品"],
            "KQ26143",
        )

        self.assertEqual(result.selected, "KQ26143 产品")

    def test_prefers_110_then_smallest_size(self) -> None:
        """验证优先 110 码且缺少时选择最小尺码。"""
        preferred = select_representative_size(
            [Path("KQ26143-蓝色-100.btw"), Path("KQ26143-蓝色-110.btw")]
        )
        fallback = select_representative_size(
            [Path("KQ26143-蓝色-120.btw"), Path("KQ26143-蓝色-100.btw")]
        )

        self.assertEqual(preferred.selected.name, "KQ26143-蓝色-110.btw")
        self.assertEqual(fallback.selected.name, "KQ26143-蓝色-100.btw")
        self.assertIn("最小尺码 100", fallback.reason)


class SourceAndFontTests(unittest.TestCase):
    """验证工作副本隔离和 Skill 字体资产。"""

    def test_source_copy_and_finished_copy_preserve_original(self) -> None:
        """验证原始包与成品包均在副本中处理。"""
        with TemporaryDirectory() as temp_dir_value:
            root = Path(temp_dir_value)
            product = root / "产品A"
            data_pack = product / "数据包"
            data_pack.mkdir(parents=True)
            (data_pack / "源文件.txt").write_text("原始", encoding="utf-8")
            self.assertEqual(detect_source_kind(product), "product")

            copied = create_local_copy(product, root / "工作区")
            (copied.working_copy / "数据包" / "源文件.txt").write_text(
                "副本",
                encoding="utf-8",
            )
            self.assertEqual((data_pack / "源文件.txt").read_text(encoding="utf-8"), "原始")

            finished = root / "全平台包"
            (finished / "天猫通用版").mkdir(parents=True)
            (finished / "京东").mkdir()
            modified = create_modified_copy(finished, root / "输出")
            self.assertEqual(modified.kind, "finished-pack")
            self.assertTrue(modified.working_copy.is_dir())
            self.assertTrue(finished.is_dir())

    def test_all_font_assets_load_and_cover_roles(self) -> None:
        """验证四个字体文件的内部名称和必需字形。"""
        assets = load_font_assets()

        self.assertEqual(set(assets), {"方正兰亭中黑", "方正兰亭中黑备用", "G8321", "数字1"})
        require_glyphs(assets["方正兰亭中黑"], "面料：棉95%")
        require_glyphs(assets["G8321"], "023456789.")
        require_glyphs(assets["数字1"], "1")
        with self.assertRaisesRegex(RuntimeError, "缺少字形"):
            require_glyphs(assets["G8321"], "%")


if __name__ == "__main__":
    unittest.main()
