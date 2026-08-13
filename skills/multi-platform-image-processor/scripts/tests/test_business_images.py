from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image

from common.bartender_exporter import export_bartender_image, fingerprint
from common.certificate_composer import compose_certificate, compose_hangtag
from common.font_assets import load_font_assets
from common.material_editor import (
    TextStyle,
    draw_mixed_text,
    replace_material_text,
    split_font_runs,
    verify_non_target_unchanged,
    wrap_mixed_text,
)
from common.size_table_extractor import CropBox, compose_size_image, extract_size_table


class BarTenderExporterTests(unittest.TestCase):
    """验证 BarTender 只读导出和失败保护。"""

    def test_export_keeps_source_fingerprint(self) -> None:
        """验证成功导出前后 `.btw` 指纹一致。"""
        with TemporaryDirectory() as temp_dir_value:
            root = Path(temp_dir_value)
            install = root / "BarTender"
            assembly = install / "SDK" / "Assemblies" / "Seagull.BarTender.Print.dll"
            assembly.parent.mkdir(parents=True)
            assembly.write_bytes(b"sdk")
            (install / "BarTend.exe").write_bytes(b"exe")
            source = root / "KQ26143-蓝色-110.btw"
            source.write_bytes(b"bartender-source")
            output = root / "export.png"
            before = fingerprint(source)

            def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
                output_index = command.index("-Output") + 1
                Image.new("RGB", (600, 300), "white").save(command[output_index])
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

            with patch("common.bartender_exporter.shutil.which", return_value="powershell.exe"), patch(
                "common.bartender_exporter.subprocess.run",
                side_effect=fake_run,
            ):
                result = export_bartender_image(source, output, install)

            self.assertEqual(result, output)
            self.assertEqual(before, fingerprint(source))
            self.assertTrue(output.is_file())

    def test_source_change_during_export_is_failure(self) -> None:
        """验证导出过程触碰源文件时立即失败。"""
        with TemporaryDirectory() as temp_dir_value:
            root = Path(temp_dir_value)
            install = root / "BarTender"
            assembly = install / "SDK" / "Assemblies" / "Seagull.BarTender.Print.dll"
            assembly.parent.mkdir(parents=True)
            assembly.write_bytes(b"sdk")
            (install / "BarTend.exe").write_bytes(b"exe")
            source = root / "KQ26143-110.btw"
            source.write_bytes(b"source")

            def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
                source.write_bytes(b"changed")
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

            with patch("common.bartender_exporter.shutil.which", return_value="powershell.exe"), patch(
                "common.bartender_exporter.subprocess.run",
                side_effect=fake_run,
            ):
                with self.assertRaisesRegex(RuntimeError, "发生变化"):
                    export_bartender_image(source, root / "export.png", install)


class BusinessImageComposerTests(unittest.TestCase):
    """验证合格证、吊牌和尺码图的固定交付尺寸。"""

    @staticmethod
    def _make_certificate(path: Path) -> None:
        image = Image.new("RGB", (900, 500), "white")
        for x in range(120, 780):
            for y in range(80, 420):
                if x in {120, 779} or y in {80, 419}:
                    image.putpixel((x, y), (30, 30, 30))
        image.save(path)

    def test_certificate_and_hangtag_sizes(self) -> None:
        """验证两种合格证图片使用白底和固定画布。"""
        with TemporaryDirectory() as temp_dir_value:
            root = Path(temp_dir_value)
            source = root / "export.png"
            self._make_certificate(source)
            certificate = compose_certificate(source, root / "合格证" / "合格证图.jpg")
            hangtag = compose_hangtag(source, root / "吊牌图" / "吊牌图.jpg")

            with Image.open(certificate) as image:
                self.assertEqual(image.size, (750, 1600))
                self.assertGreater(min(image.getpixel((0, 0))), 245)
            with Image.open(hangtag) as image:
                self.assertEqual(image.size, (800, 800))
                self.assertGreater(min(image.getpixel((0, 0))), 245)
            self.assertLessEqual(certificate.stat().st_size, 500 * 1024)
            self.assertLessEqual(hangtag.stat().st_size, 500 * 1024)

    def test_certificate_includes_excel_chinese_material(self) -> None:
        """验证合格证图使用方正字体加入中文面料。"""
        with TemporaryDirectory() as temp_dir_value:
            root = Path(temp_dir_value)
            source = root / "export.png"
            self._make_certificate(source)
            output = compose_certificate(
                source,
                root / "合格证" / "合格证图.jpg",
                fabric_text="面料：棉95%氨纶5%",
                fabric_anchor=(360, 100),
                fabric_font=load_font_assets()["方正兰亭中黑"],
                font_size=20,
            )

            with Image.open(output) as image:
                self.assertEqual(image.size, (750, 1600))
            self.assertLessEqual(output.stat().st_size, 500 * 1024)

    def test_size_table_crop_and_size_image_are_complete(self) -> None:
        """验证显式裁切保留表格底边并生成 800×800 尺码图。"""
        with TemporaryDirectory() as temp_dir_value:
            root = Path(temp_dir_value)
            source = root / "detail.png"
            detail = Image.new("RGB", (1000, 1000), "white")
            for y in (300, 400, 500, 600, 700):
                for x in range(100, 901):
                    detail.putpixel((x, y), (0, 0, 0))
            for x in (100, 300, 500, 700, 900):
                for y in range(300, 701):
                    detail.putpixel((x, y), (0, 0, 0))
            detail.save(source)
            table = extract_size_table(source, root / "table.png", CropBox(100, 300, 901, 701))
            with Image.open(table) as image:
                self.assertEqual(image.size, (801, 401))
                self.assertEqual(image.getpixel((0, 400)), (0, 0, 0))

            certificate = root / "certificate.png"
            self._make_certificate(certificate)
            result = compose_size_image(certificate, table, root / "尺码图" / "尺码图.jpg")
            with Image.open(result) as image:
                self.assertEqual(image.size, (800, 800))
            self.assertLessEqual(result.stat().st_size, 500 * 1024)


class MaterialProcessingTests(unittest.TestCase):
    """验证面料内容比较、混合字体和非目标区域保护。"""

    def test_font_runs_assign_digit_one_separately(self) -> None:
        """验证中文、普通数字和数字 1 使用对应字体角色。"""
        runs = split_font_runs("棉11.5%")

        self.assertEqual(
            runs,
            [
                ("方正兰亭中黑", "棉"),
                ("数字1", "11"),
                ("G8321", ".5"),
                ("方正兰亭中黑", "%"),
            ],
        )
        lines = wrap_mixed_text("棉95%氨纶5%", load_font_assets(), 36, 120)
        self.assertGreater(len(lines), 1)

    def test_repaint_changes_only_target_region(self) -> None:
        """验证面料重绘不改变指定区域以外的像素。"""
        with TemporaryDirectory() as temp_dir_value:
            root = Path(temp_dir_value)
            source = root / "before.png"
            output = root / "after.png"
            Image.new("RGB", (900, 300), (245, 245, 245)).save(source)
            region = (100, 80, 800, 180)

            replace_material_text(
                source,
                output,
                region,
                "棉95%氨纶5%",
                load_font_assets(),
                TextStyle(36, (20, 20, 20)),
                (245, 245, 245),
                (10, 15),
            )

            self.assertTrue(verify_non_target_unchanged(source, output, [region]))
            with Image.open(output) as image:
                self.assertNotEqual(image.crop(region).getbbox(), None)

    def test_repaint_right_aligns_each_excel_line(self) -> None:
        """验证 Excel 面料原文的每一行使用同一右边界。"""
        with TemporaryDirectory() as temp_dir_value:
            root = Path(temp_dir_value)
            source = root / "before.png"
            output = root / "after.png"
            Image.new("RGB", (900, 300), (245, 245, 245)).save(source)

            with patch(
                "common.material_editor.draw_mixed_text",
                wraps=draw_mixed_text,
            ) as draw:
                replace_material_text(
                    source,
                    output,
                    (100, 60, 800, 220),
                    "面料：面层：80%聚酯纤维\n底层：100%聚酯纤维",
                    load_font_assets(),
                    TextStyle(30, (20, 20, 20)),
                    (245, 245, 245),
                    (10, 10),
                )

            first_x = draw.call_args_list[0].args[1][0]
            second_x = draw.call_args_list[1].args[1][0]
            self.assertGreater(second_x, first_x)


if __name__ == "__main__":
    unittest.main()
