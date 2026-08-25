---
name: multi-platform-source-pack-audit
description: 对视觉部交付的 KOCOTREE 服装及配饰原始数据包执行多平台处理前质检，逐目录、逐文件、逐图片检查输入包结构与命名、产品信息、服饰 Logo、检测报告、中文文案、单位、字体字形、色差、透明图、详情页、平台驳回词和广告合规，并生成带图片证据的飞书错误清单。用于原始数据包进入 multi-platform-image-processor 前的检查、复查、准入审核和人工处理定位。
---

# 多平台原始数据包质检

## 审核范围

- 检查原始包中实际存在且按业务应提供的主图、SKU、白底图、透明图、详情页、素材图和随包资料。
- 对原始包中已有的合格证、吊牌图和尺码图进行内容检查。
- 审核任务只允许向 `scripts/work/<任务标识>` 和最终飞书报告写入运行产物。
- 除非用户明确要求修复，否则不修改原始数据包、Skill 内的脚本、配置、参考资料和资源文件。
- Skill 资源无法读取时，记录失败路径和原因，将受影响的专项标记为“待补证”，继续执行其他质检项目。

## 资料路由

每次审核先读取以下核心资料：

1. [references/source-pack-rules.md](references/source-pack-rules.md)：原始输入包判定规则和排除项。
2. [references/quality-check-coverage.md](references/quality-check-coverage.md)：17 项基础问题类型和全包专项。
3. [references/execution-checklist.md](references/execution-checklist.md)：逐款、逐模块完成条件。
4. [references/report-structure.md](references/report-structure.md)：飞书错误清单结构和证据字段。
5. [references/visual-review.md](references/visual-review.md)：四边、内部接缝、逐字复核和完成校验协议。
6. [references/material-review.md](references/material-review.md)：具体面料成分依据、逐图材质台账和判定口径。

按任务内容读取以下专项资料：

- 检查17项历史问题形态时，读取 [references/historical-error-examples.md](references/historical-error-examples.md)，只打开当前检查项对应的示例图。
- 每次审核执行 [references/platform-prohibited-terms.md](references/platform-prohibited-terms.md)；平台或类目未明确时扫描全部规则并将命中项标记为“待补证”。
- 商品适用平台和类目明确时，读取 [references/platform-image-requirements.md](references/platform-image-requirements.md) 中对应平台部分。
- 原始包含详情页时，读取 [references/typography-review.md](references/typography-review.md)。
- 目录命名脚本自动加载 [assets/configs/source-pack-naming-rules.json](assets/configs/source-pack-naming-rules.json)。
- 字体脚本自动加载 [assets/configs/typography-profiles.json](assets/configs/typography-profiles.json)。
- 视觉复核脚本自动加载 [assets/configs/visual-review-rules.json](assets/configs/visual-review-rules.json)。
- 驳回词扫描和完整审核校验分别加载 [assets/configs/platform-prohibited-terms.json](assets/configs/platform-prohibited-terms.json) 与 [assets/configs/audit-completion-rules.json](assets/configs/audit-completion-rules.json)。

## NAS 参考来源

每款审核前通过 Windows 网络共享读取并匹配以下三个目录：

- 产品信息：`\\192.168.110.20\浙江酷趣\产品中心\产品信息`
- 服饰 Logo 参考素材：`\\192.168.110.20\视觉部-同步\2-静物图\静物拍摄2026`
- 检测报告：`\\192.168.110.20\浙江酷趣\产品中心\检测报告`

使用文件系统工具直接访问以上 UNC 路径。若因网络未连接、共享凭据缺失、无权限或目录不存在而无法读取，在依赖该来源进行判断前说明具体目录和原因，将其标记为“未读取”。未读取的来源不得作为通过依据，相关结论标记为“待补证”。

## 执行流程

### 1. 确认输入

- 获取原始数据包的可访问路径，并确认审核全部商品还是指定货号。
- 确认商品货号、款名、品类、颜色和适用平台。
- 确认输入确为视觉部原始包，不以目录名称代替内容判断。
- 记录缺少的产品信息、Logo、检测报告或平台规则，不静默忽略。

### 2. 建立全量台账

所有 Python 脚本统一在 Skill 的 `scripts` 目录运行。`uv` 项目文件、锁文件和虚拟环境分别固定为 `scripts/pyproject.toml`、`scripts/uv.lock` 和 `scripts/.venv`。

所有台账、截图、长图、OCR、PDF 提取、证据图和报告中间文件统一放在 `scripts/work/<任务标识>`。`scripts/work-config.json` 将工作目录容量上限设为200 MiB；脚本运行前后检查容量，超限时优先清理最旧任务，并保护当前任务目录。

首次运行或依赖发生变化时，在 `scripts` 目录同步环境：

```powershell
Set-Location "<Skill目录>/scripts"
uv sync --locked
```

在同一目录生成台账：

```powershell
uv run python .\build_inventory.py "<原始数据包路径>" --output ".\work\<任务标识>\inventory.csv" --summary-output ".\work\<任务标识>\inventory-summary.json"
```

检查汇总文件的 `typography_resources` 字段。状态为 `partial` 或 `unavailable` 时，将字体专项标记为“待补证”，保留错误路径和原因，并继续其他检查。审核任务中不创建、替换或修改 Skill 资源。

生成目录与文件命名质检结果：

```powershell
uv run python .\validate_source_pack_naming.py "<原始数据包路径>" --output ".\work\<任务标识>\source-pack-naming-audit.json"
```

为配置范围内的图片生成四边和内部接缝辅助审阅图：

```powershell
uv run python .\generate_edge_review_sheets.py "<原始数据包路径>" --output-dir ".\work\<任务标识>\edge-review"
```

产品信息为旧版 `.xls` 工作簿时，使用锁定环境中的 `xlrd` 只读提取工作表：

```powershell
uv run python -X utf8 .\extract_xls.py "<产品信息表.xls>" --output ".\work\<任务标识>\product-info.json"
```

核对 JSON 中的源文件路径、SHA-256、工作表名称、行列数、合并区域和单元格数据。该脚本只读输入工作簿，仅在当前任务工作目录写入 JSON。

可单独检查或清理工作目录：

```powershell
uv run python .\cleanup_work.py
```

人工完成字体专项台账后执行闭环校验：

```powershell
uv run python .\validate_typography_review.py ".\work\<任务标识>\inventory.csv" --summary-output ".\work\<任务标识>\typography-review-summary.json"
```

人工完成四边、内部接缝、文字和材质专项台账后扫描平台驳回词：

```powershell
uv run python .\scan_prohibited_terms.py ".\work\<任务标识>\inventory.csv" --output ".\work\<任务标识>\prohibited-term-audit.json"
```

平台或类目明确时追加 `--platform "<平台>"`、`--category "<类目>"`；多个值分别重复传入对应参数。

逐条填写 `prohibited-term-audit.json` 中的 `review_status`、`review_notes` 和 `evidence_path`，再执行完整审核校验：

```powershell
uv run python .\validate_audit_completion.py ".\work\<任务标识>\inventory.csv" --prohibited-term-audit ".\work\<任务标识>\prohibited-term-audit.json" --summary-output ".\work\<任务标识>\audit-completion-summary.json"
```

不要在 Skill 根目录或其他目录创建该 Skill 的虚拟环境和运行产物。台账用于登记货号、模块、文件属性、重复关系、逐图专项状态和证据状态；命名质检结果用于记录十项输入包目录与命名检查状态。自动字段只提供候选信息，不能代替逐张放大目视检查。

### 3. 逐款全量检查

- 一个款一个款审核，每款完成全部模块后再开始下一款。
- 按 `source-pack-naming-audit.json` 复核根目录、六类一级目录、素材归属、尺寸目录、颜色命名与对应关系、透明 PNG、编号解析、重复编号和系列命名一致性。
- 每张图片必须有目视状态；台账图片总数必须等于完成目视检查的图片数。
- 按 [references/visual-review.md](references/visual-review.md) 记录每张图片的四边状态、文字存在性和全部适用文字专项；详情模块同时记录内部接缝状态。
- 联系表、缩略图、OCR、取色、哈希、Alpha 检查和拼接长图只能辅助定位。
- 按商品适用平台和类目执行 [references/platform-prohibited-terms.md](references/platform-prohibited-terms.md)，逐张核对图片中的可见文字。
- 按 [references/material-review.md](references/material-review.md) 判断每张图片是否包含材质文案，并将每处材质文案与当前款具体面料成分信息表逐项核对。
- 按图片适用平台和类型执行 [references/platform-image-requirements.md](references/platform-image-requirements.md)，核对真实像素、文件大小、数量、编号、命名和版式备注。
- 按 [references/typography-review.md](references/typography-review.md) 遍历全部详情页切片，逐个定位并比对数字 `1` 的字体和字重。
- 按 [references/execution-checklist.md](references/execution-checklist.md) 完成全部专项。

### 4. 详情页联审

- 按实际展示顺序拼接同款详情页长图，检查上下文、顺序、重复、缺失和模块衔接。
- 再回到每张原始切片检查文字、Logo、商品画面、遮挡以及上、右、下、左四边。
- 检查连续品牌横条左右端、1–3 px 非设计性白边或窄边，以及图片内部模块的白缝、断层和未贴合。
- 对可见文字完成转录，逐项检查错漏字、语法、语义和商品语境中的动词搭配。
- 边缘问题按有效视觉损失判断：关键结构缺失或明显破坏排版列为错误，影响不明确进入人工复核，仅触边且不影响阅读和画面效果时通过。
- 对详情页每一次数字 `1` 完成阿里妈妈方圆体 SemiBold 标准字形比对，并记录发现、已检查、异常和未检查数量。
- 拼接长图只作为内部辅助，最终只使用原始切片或能精确定位问题的最小截图。

### 5. 交叉比对

- 产品信息：核对货号、品名、品类、颜色、尺码、执行标准、安全类别、等级、成分名称、百分比、部位和限定语。具体面料成分信息表列出纤维明细时，图片中的“其他”不能替代明细。
- 服饰 Logo：核对形状、颜色、比例、方向、版本、字样、组合关系和落位。
- 检测报告：确认报告对应当前款和样品，再核对项目、数值、单位、结论、适用范围、限定条件和编号。
- 每款分别记录三项来源的读取与匹配状态；无差异也明确写“已核对，未发现不一致”。

### 6. 证据与结论

- 每条视觉问题旁紧跟对应原图或最小问题截图。
- 使用红框、箭头或高亮精确标注真实错误位置，并保留少量上下文。
- 每条问题写明货号、严重度、状态、相对路径、文件名、具体位置、现状、判定依据和修改建议。
- 事实不足时使用“待补证”或“待人工复核”，说明缺少的证据和复核方法。
- 功能性或性能性主张缺少对应报告、报告范围不足或平台适用性尚未确认时使用“待补证”，并列明需要的报告编号、页码、检测项目和适用范围。
- 自动检测只形成候选问题；涉及色差、实拍 Logo、语义和报告支撑范围时必须结合人工判断。
- 平台驳回词命中项必须写入飞书错误清单，注明适用平台、产品类目、命中文字、完整语境、规则依据和处理建议。
- 材质成分差异必须写入飞书错误清单，并列出图片原文、具体面料成分信息表原文、差异项和对照证据。
- 平台图片规格不符合项必须写入飞书错误清单，注明平台、图片类型、实际值、要求值和处理建议。
- 原始包目录或文件命名不符合项必须写入飞书错误清单，注明检查项、实际路径、实际名称、期望规则和修改建议。
- 同一字体问题可合并成一个条目，但必须列出全部受影响文件、位置和数量。

### 7. 飞书交付

使用 `lark-doc` 按 [references/report-structure.md](references/report-structure.md) 创建一份正式飞书云文档。多款放在同一文档并按货号独立分区。创建完成后反向读取文档，确认逐款章节、问题说明和图片证据实际存在，再返回可访问链接。

## 完成门槛

只有同时满足以下条件才可宣称完成：

1. 已确认审核对象为视觉部原始输入包。
2. 六个核心参考文件已完整读取，适用于当前模块和平台的专项资料已按需读取。
3. 三个 NAS 参考目录均已读取，或已在审核前明确记录无法读取的目录和限制。
4. 台账图片总数与逐张目视完成数一致，未检查数为零。
5. 每款所有专项均有明确状态。
6. 所有视觉问题都有相邻、准确的图片证据。
7. 详情页四边已完成二次复核。
8. 平台驳回词命中项已全部写入飞书文档并附证据。
9. 平台图片规格不符合项已全部写入飞书文档。
10. 阿里妈妈方圆体 SemiBold 字体文件和标准字形参考图已成功读取。
11. 详情页数字 `1` 的发现数量等于已检查数量，未检查数量为零；异常位置已全部写入台账和飞书文档。
12. 飞书文档已反向读取验证。
13. 原始包目录与文件命名十项检查均已完成，所有不符合项已写入飞书文档。
14. 平台驳回词扫描已覆盖全部可读文字，全部命中项均有处理状态、说明和适用证据。
15. 材质文案存在性判断覆盖全部图片，全部材质文案均已关联具体面料成分依据或标记待补证。
16. `audit-completion-summary.json` 的 `valid` 为 `true`；非零退出码时禁止创建最终飞书报告或宣称完成。
