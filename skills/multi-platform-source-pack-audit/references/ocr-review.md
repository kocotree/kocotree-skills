# OCR 文字质检

本规范定义全包图片文字识别、人工校正和六类文字专项的共用流程。OCR 用于提高文字发现率，最终结论必须结合原图、商品资料、检测报告和平台规则人工确认。

## 执行方式

在 `scripts` 目录运行：

```powershell
uv run python .\run_ocr.py "<原始数据包路径>" ".\work\<任务标识>\inventory.csv" --results-output ".\work\<任务标识>\ocr-results.json" --evidence-dir ".\work\<任务标识>\ocr-review"
```

脚本使用 RapidOCR 和 ONNX Runtime 本地识别图片，不上传原始数据包。每张图片生成文字块、四点坐标、置信度、全文、候选审核范围和标注复核图，并回填 `inventory.csv`。

## 台账字段

- `ocr_status`：`success`、`no_text` 或 `failed`。
- `ocr_engine`：OCR 引擎与运行后端版本。
- `ocr_block_count`：识别到的文字块数量。
- `ocr_mean_confidence`：文字块平均置信度。
- `ocr_low_confidence_count`：低于配置阈值的文字块数量。
- `ocr_text`：OCR 原始全文，不进行人工改写。
- `ocr_review_scopes`：由配置生成的六类候选范围；人工发现遗漏范围时追加对应 ID。
- `ocr_result_path`：当前图片在 `ocr-results.json` 中的位置。
- `ocr_evidence_path`：带文字框序号和置信度的复核图。
- `ocr_human_verified`：对照原图完成复核后填写 `true`。
- `ocr_review_notes`：OCR 错识、漏识、人工转录和降级处理说明。
- `visible_text_transcript`：人工确认后的完整可见文字，供后续规则扫描和语义检查使用。

## 六类文字专项

| 范围 ID | 质检内容 | 对应状态字段 |
|-|-|-|
| `prohibited_terms` | 平台违禁词、绝对化用语、证据型宣传和完整语境 | `ad_compliance_status` |
| `typo` | 错别字、漏字、多字、语法、动词搭配、数字和标点 | `typo_status` 等文字专项字段 |
| `material_composition` | 成分名称、比例、部位、限定语及具体面料成分依据 | `material_claim_presence_status` 及材质专项字段 |
| `size_chart` | 尺码、表头、数值、单位、行列关系和相邻尺码趋势 | `size_unit_status` |
| `product_identity` | 货号、品名、颜色、规格、SKU 和跨图片商品身份 | `identity_check_status` |
| `execution_standard` | 执行标准、安全类别、产品等级和标准编号 | `execution_standard_status` |

候选范围来自 [OCR 审核配置](../assets/configs/ocr-review-rules.json)。关键词或正则没有命中时仍需查看原图；人工发现适用范围后，将范围 ID 追加到 `ocr_review_scopes` 并完成对应状态。

## 人工复核

1. 对照原图逐块检查 `ocr-results.json` 和标注复核图。
2. 在 `visible_text_transcript` 中修正错字、数字、字母、标点、换行和阅读顺序。
3. OCR 原文与人工转录不一致时，在 `ocr_review_notes` 写明关键修正。
4. 低置信度文字块必须放大原图核对；置信度高不代表文字或语义一定正确。
5. OCR 未识别文字时手工补录，并追加适用的审核范围。
6. OCR 失败时人工判断 `text_presence_status`；含文字图片必须手工转录全文并完成六类适用专项。
7. 完成复核后填写 `ocr_human_verified=true`。

## 完成条件

- OCR 结果中的图片数量等于台账图片数量。
- 每张图片均有 OCR 状态和结构化结果，失败图片包含人工降级说明。
- 每张图片均已对照原图复核，`ocr_human_verified` 为 `true`。
- 每张含文字图片均包含 `prohibited_terms` 和 `typo` 范围。
- 材质、尺码、商品身份和执行标准候选范围均已完成对应专项状态。
- OCR 规则配置、图片哈希和结构化结果与当前台账一致。
