"""验证规格图片排序前缀清理及平台范围。"""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PIL import Image

from common.sku_naming import sku_output_path
from common.utils import new_report
from common.quality_audit import audit_sku_branch_outputs
from platforms.tmall import _copy_sku_tree
from platforms.fengxiang_aikucun import _copy_sku800_tree
from platforms.offsite import _sku_output_path


class SkuNamingTests(unittest.TestCase):
    """覆盖前缀格式、规格保护、重名以及实际输出。"""

    def test_prefix_formats_and_preserved_names(self):
        """只去掉明确排序前缀，保留纯数字、无分隔符和有效规格。"""
        for prefix in ("01_", "02-", "03 ", "01.", "01、", "(01)", "（01）", "【01】", "[01]", "01__ "):
            with self.subTest(prefix=prefix):
                self.assertEqual(sku_output_path(Path(f"01_分支/{prefix}颜色甲_02.jpg"), set()),
                                 Path("01_分支/颜色甲_02.jpg"))
        for name in ("01", "601", "110码_颜色甲", "2件套_颜色甲", "3D灰", "01颜色甲", "1.5L_颜色甲", "01_", "颜色甲_02"):
            with self.subTest(name=name):
                self.assertEqual(sku_output_path(Path(name + ".jpg"), set()), Path(name + ".jpg"))

    def test_platform_outputs_and_collision_audit(self):
        """验证SKU跨平台清理、重名不覆盖，目录及原始图片保持不变。"""
        with TemporaryDirectory() as temp:
            root = Path(temp)
            sku = root / "SKU"
            sources = []
            for index in (1, 2):
                source = sku / f"01_款式/800/0{index}_颜色甲.jpg"
                source.parent.mkdir(parents=True, exist_ok=True)
                Image.new("RGB", (20, 20), (index * 70, 20, 30)).save(source)
                sources.append(source)
            original_bytes = [source.read_bytes() for source in sources]
            directories = {"tmall": root / "out/天猫", "fengxiang-aikucun": root / "out/蜂享家"}
            report = new_report(root, None, root / "out")
            _copy_sku_tree(root, directories["tmall"] / "sku", report)
            _copy_sku800_tree(root, directories["fengxiang-aikucun"] / "800sku", report)
            for key, subdir in (("tmall", "sku"), ("fengxiang-aikucun", "800sku")):
                directory = directories[key] / subdir / "01_款式/800"
                self.assertEqual(sorted(p.name for p in directory.glob("*.jpg")), ["颜色甲.jpg", "颜色甲_2.jpg"])
            used = set()
            outputs = [_sku_output_path(source, sku, root / "offsite", used) for source in sources]
            self.assertEqual(outputs, [root / "offsite/01_款式/800/颜色甲.jpg", root / "offsite/01_款式/800/颜色甲_2.jpg"])
            audit_sku_branch_outputs(root, directories, report)
            self.assertFalse(report["失败项"])
            self.assertEqual([source.read_bytes() for source in sources], original_bytes)
