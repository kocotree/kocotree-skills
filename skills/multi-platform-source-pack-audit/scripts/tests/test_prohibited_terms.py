"""验证平台词库范围、拆字候选与原文位置。"""

import csv
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scan_prohibited_terms import (
    DEFAULT_CONFIG,
    find_term_occurrences,
    load_config,
    scan_inventory,
)


class ProhibitedTermsTests(unittest.TestCase):
    """确保蜂享家候选覆盖和原文定位可用于后续复核。"""

    def test_variants_preserve_original_spans(self):
        """拆字、全角和格式字符命中后仍准确定位原文。"""
        text = "首\n席 顶 级 ＴＯＰ１ NO．1 顶\u200b级"
        hits = find_term_occurrences(text, ["首", "首席", "顶级", "TOP1", "NO.1"])
        self.assertEqual(
            [hit["term"] for hit in hits],
            ["首\n席", "顶 级", "ＴＯＰ１", "NO．1", "顶\u200b级"],
        )
        for hit in hits:
            self.assertEqual(text[hit["start"]:hit["end"]], hit["term"])

    def test_platform_scope_and_unknown_platform(self):
        """蜂享家明确命中，未知平台需补证，其他平台不继承新增词条。"""
        config = load_config(DEFAULT_CONFIG)
        with tempfile.TemporaryDirectory() as directory:
            inventory = Path(directory) / "inventory.csv"
            row = {
                "relative_path": "详情/示例.jpg",
                "is_image": "true",
                "text_presence_status": "present",
                "visible_text_transcript": "首席 顶级",
            }
            with inventory.open("w", newline="", encoding="utf-8-sig") as target:
                writer = csv.DictWriter(target, fieldnames=list(row))
                writer.writeheader()
                writer.writerow(row)
            for platforms, disposition in [(["蜂享家"], "issue"), ([], "needs_evidence")]:
                result = scan_inventory(inventory, config, platforms, [])
                hits = [hit for hit in result["hits"] if "fengxiangjia-superlatives" in hit["matched_rule_ids"]]
                self.assertEqual({hit["term"] for hit in hits}, {"首席", "顶级"})
                self.assertTrue(all(hit["required_disposition"] == disposition for hit in hits))
            other = scan_inventory(inventory, config, ["爱库存"], [])
            self.assertEqual(other["hits"], [])


if __name__ == "__main__":
    unittest.main()
