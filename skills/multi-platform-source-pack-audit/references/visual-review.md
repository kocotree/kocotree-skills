# 视觉复核与完成校验

本规范定义图片四边、内部接缝和可见文字的结构化复核方法。复核结果填写到 `inventory.csv`，最终报告生成前使用脚本验证覆盖数量和证据完整性。

## 状态值

- `review_status`：图片完成全部适用目视检查后填写 `checked`。
- 适用检查项：填写 `pass`、`issue` 或 `needs_review`。
- 非适用检查项：填写 `not_applicable`。
- `text_presence_status`：填写 `present`、`absent` 或 `unreadable`。
- `issue` 表示已确认问题，必须填写专项说明和证据路径。
- `needs_review` 表示需要人工复核，必须填写专项说明。

状态集合、适用模块和审阅图参数由 [视觉复核配置](../assets/configs/visual-review-rules.json) 定义。

## 四边与内部接缝

每张适用图片分别填写：

- `edge_top_status`
- `edge_right_status`
- `edge_bottom_status`
- `edge_left_status`
- `edge_alignment_status`：四边检查的综合结论
- `edge_review_notes`
- `edge_evidence_path`

配置中的内部接缝适用模块还需填写 `internal_seam_status`。检查内容包括连续品牌横条左右端、1–3 px 非设计性白边或窄边、导出错位，以及图片内部模块之间的白缝、断层和未贴合。

在 `scripts` 目录生成辅助审阅图：

```powershell
uv run python .\generate_edge_review_sheets.py "<原始数据包路径>" --output-dir ".\work\<任务标识>\edge-review"
```

每张审阅图包含原图、四条边缘的近邻放大条带和内部接缝审阅区域。`edge-review-manifest.json` 记录源文件与审阅图的对应关系。审阅图只用于辅助观察，问题结论以原始图片和实际视觉损失为准。

## 可见文字

每张图片先填写 `text_presence_status`：

- `present`：填写 `visible_text_transcript`，并完成 `typo_status`、`missing_extra_character_status`、`grammar_status`、`verb_collocation_status` 和综合字段 `text_content_status`。
- `absent`：上述五个文字检查字段填写 `not_applicable`。
- `unreadable`：上述五个文字检查字段填写 `not_applicable`，在 `text_review_notes` 说明无法辨认的原因、范围和后续处理方式。

转录覆盖图片中的所有可见文字，包括标题、正文、角标、脚注、尺码、单位、数字、英文和标点。逐字复核同时检查：

- 错别字、同音或近音误用；
- 漏字、多字、错序和重复文字；
- 语法、语义、上下文和前后矛盾；
- 商品使用语境中的动词搭配，例如服装使用“穿”、帽子和眼镜等佩戴类使用“戴”。

文字专项为 `issue` 时填写 `text_review_notes` 和 `text_evidence_path`；为 `needs_review` 时填写 `text_review_notes`。

## 完成校验

完成全部人工复核后运行：

```powershell
uv run python .\validate_visual_review.py ".\work\<任务标识>\inventory.csv" --summary-output ".\work\<任务标识>\visual-review-summary.json"
```

校验器按照实际图片数量计算完成基数：

- 图片目视完成数等于图片总数；
- 四边完成数等于适用图片数乘以 4；
- 内部接缝完成数等于配置适用图片数；
- 文字存在性判断数等于图片总数；
- 文字专项完成数等于含文字图片数乘以 4；
- 已确认问题包含问题摘要和证据路径。

`visual-review-summary.json` 的 `valid` 为 `true` 后，视觉复核达到报告交付条件。文件中的 `stats` 用于填写报告覆盖数量，`errors` 用于定位未完成字段。
