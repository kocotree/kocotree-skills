# 材质成分核对

本规范定义图片材质文案与当前款具体面料成分信息的核对方法。每张图片的结果填写到 `inventory.csv`，由完整审核校验器统计覆盖数量。

## 依据口径

1. 使用当前款具体面料成分信息表中的款号、部位、纤维名称、百分比和限定语作为商品成分展示依据。
2. 检测报告用于核对报告样品、检测项目和宣传范围。报告明确覆盖当前款并直接列明成分时，将差异记录为资料冲突并结合版本和适用范围复核。
3. 主图、SKU、详情页、水洗唛、合格证和吊牌中的成分文案均与同一依据交叉核对。
4. 加号、空格、斜线、分隔符以及“面料／材质”等标题差异不构成问题。
5. 成分名称、百分比、部位或限定语发生变化属于业务内容差异。具体面料成分信息表列出纤维明细时，图片中的“其他”不能替代这些明细。

## 台账字段

每张图片先填写 `material_claim_presence_status`：

- `present`：图片包含材质或面料成分文案。
- `absent`：图片不包含材质文案。
- `unreadable`：疑似包含材质文案，但原图无法可靠辨认。

含材质文案时填写：

- `material_claim_transcript`：图片中的成分原文。
- `material_reference_status`：`matched`、`unavailable` 或 `ambiguous`。
- `material_reference_path`：具体面料成分信息表的完整路径。
- `material_reference_composition`：权威依据中的款号、部位、成分和比例原文。
- `material_composition_status`：`pass`、`issue`、`needs_review` 或 `needs_evidence`。
- `material_difference`：图片值与标准值的逐项差异。
- `material_review_notes`：判定说明和缺少的资料。
- `material_evidence_path`：已确认问题的对照证据路径。

依据不可访问或不能唯一匹配当前款时，将 `material_composition_status` 填写为 `needs_evidence`，列明需要的文件、工作表、行列、款号和版本。资料缺失不判为通过。

## 完成条件

- 图片数量等于材质文案存在性判断数量。
- 每张含材质文案图片均已关联权威依据或明确标记待补证。
- 每张含材质文案图片均已完成成分名称、百分比、部位和限定语核对。
- 已确认差异包含图片原文、标准原文、具体差异和证据路径。
