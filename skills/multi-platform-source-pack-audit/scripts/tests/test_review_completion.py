"""验证 OCR 人工覆盖和字体待复核状态的闭环规则。"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from validate_audit_completion import (  # noqa: E402
    calculate_inventory_image_sha256,
    validate_ocr_reviews,
)
from validate_typography_review import validate_inventory  # noqa: E402


class ReviewCompletionTests(unittest.TestCase):
    """覆盖已检查但待人工复核的可交付场景。"""

    def test_typography_needs_review_is_completed(self) -> None:
        """字体无法定性但已检查且记录完整时应通过闭环校验。"""

        with tempfile.TemporaryDirectory() as temp_dir:
            inventory = Path(temp_dir) / "inventory.csv"
            fieldnames = [
                "relative_path",
                "typography_profile_id",
                "typography_reference_status",
                "typography_occurrence_locations",
                "typography_review_notes",
                "watch_character_found_count",
                "watch_character_checked_count",
                "watch_character_abnormal_count",
                "watch_character_needs_review_count",
                "watch_character_unreviewed_count",
            ]
            with inventory.open("w", newline="", encoding="utf-8-sig") as target:
                writer = csv.DictWriter(target, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerow(
                    {
                        "relative_path": "详情/1_01.jpg",
                        "typography_profile_id": "detail-digit-1",
                        "typography_reference_status": "checked",
                        "typography_occurrence_locations": "右上角：疑似数字 1",
                        "typography_review_notes": "低清遮挡，需查看设计源文件复核",
                        "watch_character_found_count": "1",
                        "watch_character_checked_count": "1",
                        "watch_character_abnormal_count": "0",
                        "watch_character_needs_review_count": "1",
                        "watch_character_unreviewed_count": "0",
                    }
                )

            result = validate_inventory(inventory)

        self.assertTrue(result["valid"])
        self.assertEqual(result["profiles"]["detail-digit-1"]["needs_review"], 1)

    def test_ocr_false_positive_with_human_notes_is_completed(self) -> None:
        """OCR 误识别经人工确认并说明后应通过 OCR 完成校验。"""

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "ocr-config.json"
            config_path.write_text("{}", encoding="utf-8")
            row = {
                "relative_path": "主图/红色.jpg",
                "is_image": "true",
                "sha256": "image-sha256",
                "ocr_status": "success",
                "ocr_engine": "RapidOCR",
                "ocr_block_count": "1",
                "ocr_low_confidence_count": "1",
                "ocr_text": "误识别文字",
                "ocr_review_scopes": "prohibited_terms;typo",
                "ocr_evidence_path": "ocr-review/红色.jpg",
                "ocr_human_verified": "true",
                "ocr_review_notes": "原图为纹理，没有有效文字",
                "text_presence_status": "absent",
                "visible_text_transcript": "",
                "ad_compliance_status": "not_applicable",
                "typo_status": "not_applicable",
            }
            results_path = root / "ocr-results.json"
            result_id = "image-0001"
            row["ocr_result_path"] = f"{results_path.resolve()}#{result_id}"
            results = {
                "config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
                "inventory_image_sha256": calculate_inventory_image_sha256([row]),
                "images_total": 1,
                "images": [
                    {
                        "id": result_id,
                        "relative_path": row["relative_path"],
                        "sha256": row["sha256"],
                        "status": "success",
                        "text": row["ocr_text"],
                        "review_scopes": ["prohibited_terms", "typo"],
                    }
                ],
            }
            results_path.write_text(
                json.dumps(results, ensure_ascii=False), encoding="utf-8"
            )
            config = {
                "completed_ocr_statuses": ["success", "no_text", "failed"],
                "scope_status_fields": {
                    "prohibited_terms": "ad_compliance_status",
                    "typo": "typo_status",
                },
                "scope_allowed_statuses": {
                    "prohibited_terms": ["pass", "issue", "needs_review"],
                    "typo": ["pass", "issue", "needs_review"],
                },
            }

            stats, errors = validate_ocr_reviews(
                [row], results_path, config_path, config
            )

        self.assertEqual(errors, [])
        self.assertEqual(stats["human_overrides"], 1)


if __name__ == "__main__":
    unittest.main()
