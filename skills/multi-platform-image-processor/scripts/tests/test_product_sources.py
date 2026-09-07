from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from common.product_info_reader import ProductInfoRecord, extract_chinese_material
from common.product_matcher import MatchResult
from common.product_sources import _read_table, resolve_product_data
from common.settings import config_root, load_json_config


def sku(record_id: str = "rec-a", **values: str) -> dict[str, str]:
    """构造通用测试产品的完整码表记录。"""
    return {"record_id": record_id, "产品货号": "P100", "产品名称": "测试外套",
            "中文面料": "面料：100%棉", "规格": "蓝色110", "尺码": "110/52", **values}


class ProductSourcesTests(unittest.TestCase):
    """验证两表优先、字段补缺和单次任务记录一致性。"""

    def resolve(self, rows, nas=None):
        """用可控的两表记录和 NAS 结果运行资料解析。"""
        with patch("common.product_sources._read_table", side_effect=rows), patch(
            "common.product_sources.require_accessible_directory", return_value=Path("nas"),
        ) as access, patch("common.product_sources.find_product_info", return_value=nas) as find:
            product = resolve_product_data("P100", "", Path("nas"))
        return product, access, find

    def test_complete_base_does_not_access_excel(self):
        """验证资料齐全时码表优先且不访问 NAS Excel。"""
        product, access, find = self.resolve([[sku()], [sku("rec-spu", 产品名称="款表名称")]])
        self.assertEqual(product.get("产品名称"), "测试外套")
        self.assertEqual(product.get("颜色"), "蓝色")
        self.assertEqual(product.sources["中文面料"]["来源"], "产品资料-码-对外")
        access.assert_not_called()
        find.assert_not_called()

    def test_spu_fills_missing_name(self):
        """验证款表仅补充码表缺失的名称。"""
        product, _, find = self.resolve([
            [sku(产品名称="")],
            [{"record_id": "rec-spu", "产品货号": "P100", "产品名称": "款表名称"}],
        ])
        self.assertEqual(product.get("产品名称"), "款表名称")
        self.assertEqual(product.sources["产品名称"]["来源"], "产品资料-款-对外")
        find.assert_not_called()

    def test_nas_only_fills_missing_material(self):
        """验证 NAS 只补材质，不覆盖码表名称、颜色或规格。"""
        record = ProductInfoRecord(Path("nas.xlsx"), "资料", 2,
                                   {"产品货号": "P100", "产品名称": "NAS名称",
                                    "中文面料": "100%锦纶", "颜色": "红色", "规格": "红色120"})
        product, _, find = self.resolve([[sku(中文面料="")], []], MatchResult(record, [record], "唯一"))
        self.assertEqual(product.get("中文面料"), "100%锦纶")
        self.assertEqual(product.get("产品名称"), "测试外套")
        self.assertEqual(product.get("规格"), "蓝色110")
        self.assertEqual(product.get("颜色"), "蓝色")
        self.assertEqual(product.sources["中文面料"]["文件"], "nas.xlsx")
        find.assert_called_once_with(Path("nas"), "P100")

    def test_empty_tables_use_nas(self):
        """验证两表均未找到产品时从 NAS 补齐资料。"""
        record = ProductInfoRecord(Path("nas.xlsx"), "资料", 2, sku())
        product, _, find = self.resolve([[], []], MatchResult(record, [record], "唯一"))
        self.assertEqual(product.get("产品货号"), "P100")
        self.assertEqual(product.sources["产品名称"]["来源"], "NAS Excel")
        find.assert_called_once()

    def test_selects_one_complete_stable_record(self):
        """验证同表多规格只选一条记录，顺序变化不影响选择。"""
        rows = [sku("rec-z"), sku("rec-a", 规格="绿色120", 尺码="120/56"), sku("rec-0", 中文面料="")]
        first, _, _ = self.resolve([rows, []])
        second, _, _ = self.resolve([list(reversed(rows)), []])
        self.assertEqual(first.to_report(), second.to_report())
        self.assertEqual(first.get("颜色"), "绿色")
        self.assertEqual(first.get("尺码"), "120/56")

    def test_missing_material_after_nas_is_reported(self):
        """验证所有来源均缺必要资料时报告真实缺项。"""
        with self.assertRaisesRegex(RuntimeError, "中文面料"):
            self.resolve([[sku(中文面料="")], []], MatchResult(None, [], "没有找到产品"))

    def test_authorization_failure_does_not_silently_switch_to_nas(self):
        """验证授权失败与无匹配记录区分处理。"""
        with patch("common.product_sources._read_table", side_effect=RuntimeError("用户授权失败")), patch(
            "common.product_sources.find_product_info",
        ) as find, self.assertRaisesRegex(RuntimeError, "用户授权失败"):
            resolve_product_data("P100", "", Path("nas"))
        find.assert_not_called()

    def test_cli_uses_exact_code_and_maps_empty_values(self):
        """验证 CLI 参数、精确货号复核以及英文和占位成分补缺语义。"""
        config = load_json_config(config_root() / "product_sources.json")
        table = config["tables"][0]
        def run(command, **kwargs):
            directory = kwargs["cwd"]
            query_path = directory / command[command.index("--filter-json") + 1][1:]
            self.assertEqual(json.loads(query_path.read_text(encoding="utf-8"))["conditions"][0][2], "P100")
            self.assertEqual(command[command.index("--as") + 1], "user")
            records = [
                {"record_id": "a", "货号（KQ码）": " P100 ", "品名": "外套", "成分": "Fabric: cotton"},
                {"record_id": "b", "货号（KQ码）": "P100", "成分": "/"},
                {"record_id": "c", "货号（KQ码）": "P1000", "成分": "100%棉"},
            ]
            (directory / command[command.index("--output") + 1]).write_text(
                "\n".join(json.dumps(r, ensure_ascii=False) for r in records), encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, '{"has_more":false}', "")
        with TemporaryDirectory() as temp, patch("common.product_sources.shutil.which", return_value="lark-cli"), patch(
            "common.product_sources.subprocess.run", side_effect=run,
        ):
            rows = _read_table(config, table, "P100", Path(temp))
        self.assertEqual([r["record_id"] for r in rows], ["a", "b"])
        self.assertTrue(all(r["中文面料"] == "" for r in rows))

    def test_query_limit_is_not_treated_as_complete(self):
        """验证截断查询不被当成完整候选集。"""
        config = load_json_config(config_root() / "product_sources.json")
        with TemporaryDirectory() as temp, patch("common.product_sources.shutil.which", return_value="lark-cli"), patch(
            "common.product_sources.subprocess.run", return_value=subprocess.CompletedProcess([], 0, '{"has_more":true}', ""),
        ), self.assertRaisesRegex(RuntimeError, "查询上限"):
            _read_table(config, config["tables"][0], "P100", Path(temp))


class ChineseMaterialTests(unittest.TestCase):
    """验证多维表与 Excel 的中文材质提取规则。"""

    def test_interleaved_translations_keep_all_chinese(self):
        """验证中英交错时保留后续里料与填充物。"""
        self.assertEqual(extract_chinese_material(
            "面料：100%锦纶\nFabric: 100% Nylon\n里料：100%棉\nLining: cotton\n填充物：100%聚酯纤维"
        ), "面料：100%锦纶\n里料：100%棉\n填充物：100%聚酯纤维")

    def test_inline_translation_and_chemical_symbols(self):
        """验证同行译文被排除，材质中的化学符号保持原样。"""
        self.assertEqual(extract_chinese_material(
            "里料：100%聚酯纤维ingredients:100% polyester\n杯身：06Cr17Ni12Mo2(内胆S316)"
        ), "里料：100%聚酯纤维\n杯身：06Cr17Ni12Mo2(内胆S316)")

    def test_english_and_placeholders_are_missing(self):
        """验证英文或占位符不是可用中文材质。"""
        for value in (None, "", "/", "Fabric: cotton", "—"):
            with self.subTest(value=value):
                self.assertEqual(extract_chinese_material(value), "")
