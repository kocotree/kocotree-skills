"""验证输入目录别名读取及平台标准目录输出。"""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PIL import Image

from common.scan_source_pack import resolve_source_path, source_directory_aliases, get_sku800_recursive
from common.color_naming import resolve_color_names
from common.detail_page_slice import collect_detail_sources
from common.utils import new_report
from platforms.tmall import build


class SourceDirectoryAliasTests(unittest.TestCase):
    """覆盖各分类别名、优先级及真实图片输出。"""

    def test_all_configured_aliases_resolve_without_renaming(self):
        """验证全部配置名称均读取原目录，分类下的尺寸目录保持原样。"""
        for group, aliases in source_directory_aliases().items():
            for alias in aliases:
                with self.subTest(group=group, alias=alias), TemporaryDirectory() as temp:
                    root = Path(temp)
                    directory = root / alias
                    directory.mkdir()
                    self.assertEqual(resolve_source_path(root, group), directory)
                    if group == "主图":
                        self.assertEqual(resolve_source_path(root, "主图800"), directory / "800")
                    if group == "SKU":
                        (directory / "800").mkdir()
                        image = directory / "800/a.jpg"
                        Image.new("RGB", (10, 10)).save(image)
                        self.assertEqual(get_sku800_recursive(root), [image])
                    self.assertTrue(directory.is_dir())
                    self.assertFalse((root / group).exists())

    def test_standard_directory_has_priority(self):
        """验证标准目录与别名并存时优先读取标准目录并记录警告。"""
        with TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "白底图").mkdir()
            (root / "白底").mkdir()
            with self.assertLogs("common.scan_source_pack", level="WARNING"):
                self.assertEqual(resolve_source_path(root, "白底图"), root / "白底图")

    def test_alias_package_outputs_standard_platform_directories(self):
        """验证颜色映射、分支路径、详情与主图别名贯通天猫输出，原目录保持不变。"""
        with TemporaryDirectory() as temp:
            root = Path(temp) / "source"
            for name in ("商品主图/800/a.jpg", "规格图/800/a.jpg", "白底/分支/a.jpg",
                         "透明底/分支/a.png", "产品详情/a.jpg", "场景/a.jpg"):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                Image.new("RGBA" if path.suffix == ".png" else "RGB", (20, 20)).save(path)
            colors = resolve_color_names(root, {})
            self.assertEqual(colors[(root / "白底/分支/a.jpg").resolve()], "a")
            self.assertEqual(collect_detail_sources(root), [root / "产品详情/a.jpg"])
            plan = Path(temp) / "plan.json"
            plan.write_text(json.dumps({"详情模块": [{"图片": "产品详情/a.jpg", "类型": "KV"}]}), encoding="utf-8")
            output = Path(temp) / "output"
            output.mkdir()
            report = new_report(root, None, output)
            platform = build(root, output, report, detail_plan=plan, color_names=colors)
            for name in ("主图/800主图/a.jpg", "sku/800/a.jpg", "800白底图/分支/a.jpg",
                         "800透明图/分支/a.png", "790详情页/601.jpg", "素材图/a.jpg"):
                self.assertTrue((platform / name).is_file(), name)
            self.assertFalse(report["失败项"])
            self.assertTrue((root / "透明底/分支/a.png").is_file())
            self.assertFalse((root / "透明图").exists())

    def test_images_subdirectory_is_not_collected(self):
        """验证详情别名仅改变分类目录名称，images子目录不参与读取。"""
        with TemporaryDirectory() as temp:
            root = Path(temp)
            nested = root / "详情页/images/a.jpg"
            nested.parent.mkdir(parents=True)
            Image.new("RGB", (10, 10)).save(nested)
            with self.assertRaises(ValueError):
                collect_detail_sources(root)
