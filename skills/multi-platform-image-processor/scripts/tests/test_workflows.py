from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

import main as main_module
from common.delivery_quality_audit import audit_business_images
from common.material_editor import verify_non_target_unchanged
from common.product_info_reader import ProductInfoRecord
from common.product_matcher import MatchResult
from common.utils import new_report
from common.write_report import write_report
from workflows.full_package import run_full_workflow
from workflows.material_correction import apply_material_plan
from workflows.platform_processing import run_platform_processing


class UnifiedEntryTests(unittest.TestCase):
    """验证单一完整流程入口。"""

    def test_public_arguments_are_minimal(self) -> None:
        """验证公开入口只要求源目录，并接受三个可选参数。"""
        args = main_module.parse_args(["--source", "产品"])

        self.assertEqual(args.source, "产品")
        self.assertEqual(args.output, "")
        self.assertEqual(args.product_code, "")
        self.assertEqual(args.product_name, "")

    def test_main_runs_complete_workflow(self) -> None:
        """验证入口始终调用完整处理流程。"""
        with patch("main.configure_runtime_environment"), patch(
            "main.ensure_token",
        ), patch("main.run_full_workflow", return_value=0) as runner:
            code = main_module.main(["--source", "产品"])

        self.assertEqual(code, 0)
        runner.assert_called_once()


class WorkflowReportTests(unittest.TestCase):
    """验证业务顶层报告和业务图片自动质检。"""

    def test_report_status_reflects_review_and_failures(self) -> None:
        """验证完成状态由失败项和复核项决定。"""
        with TemporaryDirectory() as temp_dir_value:
            root = Path(temp_dir_value)
            report = new_report(root, None, root)
            report["Agent复核建议"].append({"任务名称": "视觉复核"})
            path = root / "report.json"
            write_report(report, path)
            data = json.loads(path.read_text(encoding="utf-8"))

            self.assertEqual(data["工作流"]["完成状态"], "部分完成")
            self.assertEqual(data["汇总"]["Agent复核建议数"], 1)

    def test_delivery_audit_checks_fixed_sizes(self) -> None:
        """验证三张业务图片的固定路径和尺寸。"""
        with TemporaryDirectory() as temp_dir_value:
            root = Path(temp_dir_value)
            assets = {
                root / "合格证" / "合格证图.jpg": (750, 1600),
                root / "吊牌图" / "吊牌图.jpg": (800, 800),
                root / "尺码图" / "尺码图.jpg": (800, 800),
            }
            for path, size in assets.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                Image.new("RGB", size, "white").save(path, "JPEG")
            report = new_report(root, None, root)

            self.assertTrue(audit_business_images(root, report))
            self.assertFalse(report["失败项"])

    def test_delivery_audit_rejects_business_image_over_500kb(self) -> None:
        """验证业务图片超过 500KB 时记录失败项。"""
        with TemporaryDirectory() as temp_dir_value:
            root = Path(temp_dir_value)
            assets = {
                root / "合格证" / "合格证图.jpg": (750, 1600),
                root / "吊牌图" / "吊牌图.jpg": (800, 800),
                root / "尺码图" / "尺码图.jpg": (800, 800),
            }
            for path, size in assets.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                Image.new("RGB", size, "white").save(path, "JPEG")
            oversized = root / "合格证" / "合格证图.jpg"
            oversized.write_bytes(oversized.read_bytes() + b"0" * (501 * 1024))
            report = new_report(root, None, root)

            self.assertFalse(audit_business_images(root, report))
            self.assertTrue(any("超过500KB" in item["信息"] for item in report["失败项"]))


class MaterialPlanTests(unittest.TestCase):
    """验证 Agent 视觉计划驱动局部面料修正。"""

    def test_material_plan_outputs_correction_without_changing_source(self) -> None:
        """验证 JPEG 面料修正版使用无损临时图且原图保持不变。"""
        with TemporaryDirectory() as temp_dir_value:
            root = Path(temp_dir_value)
            detail = root / "数据包" / "详情" / "静态" / "601.jpg"
            detail.parent.mkdir(parents=True)
            Image.effect_noise((900, 300), 80).convert("RGB").save(
                detail,
                "JPEG",
                quality=90,
            )
            plan = root / "plan.json"
            plan.write_text(
                json.dumps(
                    {
                        "面料区域": [
                            {
                                "图片": "数据包/详情/静态/601.jpg",
                                "识别原文": "棉90%氨纶10%",
                                "区域": [100, 80, 800, 180],
                                "字号": 36,
                                "颜色": [20, 20, 20],
                                "背景色": [245, 245, 245],
                                "内边距": [10, 15],
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            report = new_report(root, None, root)
            original_bytes = detail.read_bytes()
            staging = root / "临时修正版"

            with patch(
                "workflows.material_correction.verify_non_target_unchanged",
                wraps=verify_non_target_unchanged,
            ) as verifier:
                replacements = apply_material_plan(
                    root,
                    "棉95%氨纶5%",
                    plan,
                    staging,
                    report,
                )

            self.assertIsNotNone(replacements)
            self.assertEqual(verifier.call_args.kwargs["difference_threshold"], 12)
            self.assertFalse(report["失败项"])
            self.assertTrue(report["面料检查"]["检查项"][0]["已修改"])
            self.assertEqual(detail.read_bytes(), original_bytes)
            corrected = replacements[detail.resolve()]
            self.assertTrue(corrected.is_file())
            self.assertEqual(corrected.name, "601.jpg.png")
            with Image.open(corrected) as corrected_image:
                self.assertEqual(corrected_image.format, "PNG")
            self.assertNotEqual(corrected.read_bytes(), original_bytes)


class FullWorkflowTests(unittest.TestCase):
    """验证完整流程按面料、平台、业务图片顺序编排。"""

    def test_platform_processing_preserves_confirmed_product_name(self) -> None:
        """验证平台入口使用确认产品名称生成京东目录。"""
        with TemporaryDirectory() as temp_dir_value:
            root = Path(temp_dir_value)
            source = root / "kocotree-pack-random" / "数据包"
            source.mkdir(parents=True)
            output_root = root / "输出"
            with patch(
                "workflows.platform_processing.copy_template_empty_dirs",
            ), patch(
                "workflows.platform_processing.build_tmall",
                return_value=output_root / "天猫通用版",
            ), patch(
                "workflows.platform_processing.derive_cbme",
            ), patch(
                "workflows.platform_processing.derive_jd",
            ) as derive_jd, patch(
                "workflows.platform_processing.derive_vip",
            ), patch(
                "workflows.platform_processing.derive_fengxiang_aikucun",
            ), patch(
                "workflows.platform_processing.derive_offsite",
            ), patch(
                "workflows.platform_processing.run_quality_audit",
            ):
                report = new_report(source, root / "模板", output_root)
                code, output = run_platform_processing(
                    source,
                    root / "模板",
                    output_root,
                    report,
                    product_code="KQ26143",
                    product_name="儿童长裤",
                )

            self.assertEqual(code, 0)
            expected_jd = output / "KQ26143 儿童长裤-京东"
            self.assertEqual(derive_jd.call_args.args[2], expected_jd)
            self.assertEqual(report["处理配置"]["产品名"], "儿童长裤")

    def test_full_workflow_orchestrates_all_layers(self) -> None:
        """验证完整流程使用原始输入和临时修正版生成交付包。"""
        with TemporaryDirectory() as temp_dir_value:
            root = Path(temp_dir_value)
            source = root / "产品" / "数据包"
            source.mkdir(parents=True)
            output = root / "输出"
            report_path = root / "full-report.json"
            record = ProductInfoRecord(
                root / "KQ26143.xlsx",
                "产品资料",
                2,
                {
                    "产品货号": "KQ26143",
                    "产品名称": "儿童长裤",
                    "中文面料": "棉95%氨纶5%",
                    "规格": "蓝色110",
                },
            )
            args = SimpleNamespace(
                source=str(source),
                output=str(output),
                product_code="KQ26143",
                product_name="儿童长裤",
                material_plan="plan.json",
            )
            with patch(
                "workflows.full_package.default_business_report_path",
                return_value=report_path,
            ), patch("workflows.full_package.resolve_business_paths") as resolve_paths, patch(
                "workflows.full_package.require_accessible_directory",
                side_effect=[root, root],
            ), patch(
                "workflows.full_package.find_product_info",
                return_value=MatchResult(record, [record], "唯一"),
            ), patch(
                "workflows.full_package.apply_material_plan",
                return_value={},
            ) as material, patch(
                "workflows.full_package.run_platform_processing",
                return_value=(0, output / "产品"),
            ) as platform, patch(
                "workflows.full_package.generate_business_images",
                return_value=True,
            ) as business:
                resolve_paths.return_value.product_info_root = root
                resolve_paths.return_value.certificate_root = root
                code = run_full_workflow(args)

            self.assertEqual(code, 0)
            material.assert_called_once()
            platform.assert_called_once()
            self.assertEqual(platform.call_args.kwargs["product_code"], "KQ26143")
            self.assertEqual(platform.call_args.kwargs["product_name"], "儿童长裤")
            self.assertEqual(platform.call_args.args[0], source.resolve())
            self.assertEqual(platform.call_args.kwargs["detail_overrides"], {})
            business.assert_called_once()
            self.assertEqual(business.call_args.kwargs["product_name"], "儿童长裤")
            self.assertEqual(business.call_args.kwargs["representative_color"], "蓝色")
            self.assertEqual(business.call_args.kwargs["fabric_text"], "棉95%氨纶5%")
            self.assertEqual(business.call_args.kwargs["content_root"], source.resolve())
            self.assertFalse(material.call_args.args[3].exists())
            data = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(data["工作流"]["完成状态"], "完成")


if __name__ == "__main__":
    unittest.main()
