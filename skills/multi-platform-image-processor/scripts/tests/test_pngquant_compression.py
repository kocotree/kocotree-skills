from __future__ import annotations

import json
import subprocess
import unittest
from collections.abc import Callable
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image

from common.image_resize_compress import compress_pngquant_under_limit, save_png_under
from common.utils import new_report
from common.write_report import image_records_path, write_report


def completed(command: list[str], return_code: int, stderr: str = "") -> subprocess.CompletedProcess:
    """创建用于 pngquant 调用测试的子进程结果。"""
    return subprocess.CompletedProcess(command, return_code, stdout="", stderr=stderr)


def candidate_result(size: int) -> Callable[..., subprocess.CompletedProcess]:
    """创建会写出指定大小候选文件的 pngquant 测试调用。"""

    def create(command: list[str], **_: object) -> subprocess.CompletedProcess:
        output = Path(command[command.index("--output") + 1])
        output.write_bytes(b"b" * size)
        return completed(command, 0)

    return create


class PngquantCompressionTests(unittest.TestCase):
    """验证 pngquant 执行结果、大小状态和报告统计。"""

    def run_compression(
        self,
        input_size: int,
        max_bytes: int,
        runner: Callable[..., subprocess.CompletedProcess],
    ) -> tuple[dict[str, object], bytes]:
        """使用单组质量和颜色参数执行压缩测试。"""
        with TemporaryDirectory() as temp_dir_value:
            target = Path(temp_dir_value) / "image.png"
            target.write_bytes(b"a" * input_size)
            with patch(
                "common.image_resize_compress.PNGQUANT_颜色档",
                [256],
            ), patch(
                "common.image_resize_compress.PNGQUANT_质量档",
                ["80-95"],
            ), patch(
                "common.image_resize_compress.subprocess.run",
                side_effect=runner,
            ):
                result = compress_pngquant_under_limit("/fake/pngquant", target, max_bytes)
            return result, target.read_bytes()

    def test_successful_candidate_replaces_target(self) -> None:
        """验证有效且满足大小限制的候选文件被采用。"""
        result, output = self.run_compression(200, 100, candidate_result(50))
        self.assertEqual(result["状态"], "成功")
        self.assertEqual(result["尝试次数"], 1)
        self.assertEqual(len(output), 50)

    def test_skipped_candidate_keeps_small_original(self) -> None:
        """验证候选未生成且原图符合限制时记录为保留原图。"""
        result, output = self.run_compression(80, 100, lambda *_args, **_kwargs: completed([], 98))
        self.assertEqual(result["状态"], "保留原图")
        self.assertEqual(result["退出码"], 98)
        self.assertEqual(len(output), 80)

    def test_valid_candidate_over_limit_is_reported(self) -> None:
        """验证有效候选仍超过限制时返回超出限制。"""
        result, output = self.run_compression(200, 100, candidate_result(150))
        self.assertEqual(result["状态"], "超出限制")
        self.assertEqual(len(output), 150)

    def test_nonzero_exit_is_execution_failure(self) -> None:
        """验证异常退出码不会被记录为压缩成功。"""
        result, _ = self.run_compression(
            80,
            100,
            lambda *_args, **_kwargs: completed([], 2, "参数错误"),
        )
        self.assertEqual(result["状态"], "执行失败")
        self.assertEqual(result["退出码"], 2)
        self.assertIn("参数错误", str(result["错误"]))

    def test_success_without_output_is_execution_failure(self) -> None:
        """验证成功退出但缺少输出文件时记录执行失败。"""
        result, output = self.run_compression(80, 100, lambda *_args, **_kwargs: completed([], 0))
        self.assertEqual(result["状态"], "执行失败")
        self.assertIn("没有生成输出文件", str(result["错误"]))
        self.assertEqual(len(output), 80)

    def test_main_report_contains_compact_png_statistics(self) -> None:
        """验证逐图压缩详情与主报告分类统计相互分离。"""
        with TemporaryDirectory() as temp_dir_value:
            temp_dir = Path(temp_dir_value)
            report_path = temp_dir / "产品A-report.json"
            report = new_report(temp_dir, None, temp_dir / "输出", "tmall")
            report["处理配置"].update({"运行ID": "run-001", "产品名": "产品A"})
            compression = {
                "状态": "执行失败",
                "尝试次数": 1,
                "退出码": 2,
                "输入大小KB": 1.0,
                "输出大小KB": 1.0,
                "限制KB": 0.5,
                "错误": "参数错误",
            }
            with patch(
                "common.image_resize_compress.find_pngquant",
                return_value="/fake/pngquant",
            ), patch(
                "common.image_resize_compress.compress_pngquant_under_limit",
                return_value=compression,
            ):
                save_png_under(
                    Image.new("RGBA", (10, 10), (255, 0, 0, 128)),
                    temp_dir / "output.png",
                    500,
                    report,
                    platform="天猫通用版",
                    usage="800透明图",
                )

            write_report(report, report_path)
            main_report = json.loads(report_path.read_text(encoding="utf-8"))
            detail_record = json.loads(
                image_records_path(report_path).read_text(encoding="utf-8").splitlines()[0]
            )
            self.assertEqual(main_report["PNG压缩统计"]["处理图片数"], 1)
            self.assertEqual(main_report["PNG压缩统计"]["执行失败"], 1)
            self.assertNotIn("PNG压缩", main_report)
            self.assertEqual(detail_record["PNG压缩"]["状态"], "执行失败")
            self.assertEqual(detail_record["处理结果"], "部分失败")
            self.assertEqual(len(main_report["失败项"]), 1)


if __name__ == "__main__":
    unittest.main()
