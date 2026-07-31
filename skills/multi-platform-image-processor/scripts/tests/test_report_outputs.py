from __future__ import annotations

import json
import logging
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from main import parse_args
from common.run_logging import close_run_file_logging, configure_run_file_logging
from common.utils import add_image_record, new_report
from common.write_report import image_records_path, write_report


class ReportOutputsTests(unittest.TestCase):
    """验证精简主报告、逐图明细和运行日志的输出结构。"""

    def tearDown(self) -> None:
        """关闭测试创建的运行日志处理器。"""
        close_run_file_logging()

    def test_cli_keeps_output_and_uses_automatic_report_path(self) -> None:
        """验证命令行支持成品目录且不提供报告路径参数。"""
        args = parse_args(["--source", "源数据包", "--output", "成品目录"])

        self.assertEqual(args.output, "成品目录")
        self.assertFalse(hasattr(args, "report"))

    def test_main_report_is_compact_and_image_records_are_separate(self) -> None:
        """验证主报告只保留统计，完整图片记录写入 JSONL。"""
        with TemporaryDirectory() as temp_dir_value:
            temp_dir = Path(temp_dir_value)
            source = temp_dir / "源图.jpg"
            output = temp_dir / "输出图.jpg"
            Image.new("RGB", (20, 16), (220, 220, 220)).save(source)
            Image.new("RGB", (10, 8), (210, 210, 210)).save(output)
            report_path = temp_dir / "产品A-20260731-152030-report.json"
            report = new_report(temp_dir, None, temp_dir / "输出", "tmall")
            report["处理配置"]["运行ID"] = "20260731-152030"
            report["处理配置"]["产品名"] = "产品A"
            report["追溯文件"]["运行日志"] = str(temp_dir / "logs" / "20260731-152030.log")
            add_image_record(
                report,
                source,
                output,
                "天猫通用版",
                "主图",
                ["缩放", "JPG压缩"],
            )

            write_report(report, report_path)

            main_report = json.loads(report_path.read_text(encoding="utf-8"))
            detail_path = image_records_path(report_path)
            detail_lines = detail_path.read_text(encoding="utf-8").splitlines()
            detail_record = json.loads(detail_lines[0])

            self.assertNotIn("图片记录", main_report)
            self.assertEqual(main_report["图片统计"]["总数"], 1)
            self.assertEqual(
                main_report["图片统计"]["按平台"]["天猫通用版"]["按用途"]["主图"],
                1,
            )
            self.assertEqual(main_report["汇总"]["图片数"], 1)
            self.assertEqual(main_report["追溯文件"]["逐图明细"], str(detail_path.resolve()))
            self.assertEqual(len(detail_lines), 1)
            self.assertEqual(detail_record["运行ID"], "20260731-152030")
            self.assertEqual(detail_record["产品"], "产品A")
            self.assertEqual(detail_record["输出文件"], str(output))
            self.assertEqual(detail_record["处理结果"], "成功")

    def test_run_log_contains_structured_context(self) -> None:
        """验证运行日志包含统一的运行和处理阶段字段。"""
        with TemporaryDirectory() as temp_dir_value:
            log_path = Path(temp_dir_value) / "logs" / "run.log"
            configure_run_file_logging(log_path, "run-001", "产品A")

            logging.getLogger("tests.report").info(
                "测试图片处理完成",
                extra={
                    "platform": "天猫通用版",
                    "stage": "图片处理",
                    "event": "图片完成",
                    "status": "success",
                },
            )
            close_run_file_logging()

            content = log_path.read_text(encoding="utf-8")
            self.assertIn("run_id=run-001", content)
            self.assertIn("product=产品A", content)
            self.assertIn("platform=天猫通用版", content)
            self.assertIn("stage=图片处理", content)
            self.assertIn("event=图片完成", content)
            self.assertIn("status=success", content)


if __name__ == "__main__":
    unittest.main()
