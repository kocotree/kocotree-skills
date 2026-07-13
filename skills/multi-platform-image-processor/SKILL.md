---
name: multi-platform-image-processor
description: 全自动处理商品图片数据包并输出多平台合规图片包。用于天猫通用版、京东、CBME、唯品会、蜂享家＋爱库存、站外通用版的主图、SKU、白底图、透明图、详情页、素材图分类、缩放、压缩、去字、透明裁边、切片、质检和报告生成。
metadata:
  version: "1.0.0"
---

# 多平台图片处理

## 环境准备

首次使用前需在 `scripts/` 目录下初始化 Python 环境：

```bash
cd scripts
uv sync
```

如未安装 uv，先执行：

- macOS/Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- Windows: `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`

初始化完成后，使用 `.venv` 中的 Python 执行工具脚本。

**注意**  

去除文字强依赖于 `text2image` skill，首次使用会自动安装  
首次使用该技能要求auth授权，**务必**按照提示提醒用户完成授权，**禁止跳过授权**

## 核心流程

使用 `uv + Python` 自动完成整包处理。默认流程：

1. 强制检测输入包文件夹结构和透明图主体外脏点。`SKU` 根目录大小写不限；其他标准目录名称必须准确。存在目录误命名、必需目录缺失或为空、详情结构无效、透明图无透明背景或主体外残留时，立即写报告并停止，不创建平台内容。
2. 扫描通过的数据包，识别 `主图`、`SKU`、`白底图`、`透明图`、`详情`、`素材图`。
3. 先生成天猫通用版母版，尤其是 `790详情页`。
4. 从天猫母版派生 CBME、京东、唯品会、蜂享家＋爱库存、站外通用版。
5. 执行确定性处理、模型去字、尺寸转换和压缩。
6. 由 Agent 根据报告中的复核建议处理复杂视觉判断。
7. 自动检查尺寸、格式、大小、透明通道、命名连续性和平台数量限制。
8. 输出平台文件夹和中文 JSON 报告。

## 推荐命令

在本 skill 目录下运行，注意使用虚拟环境，以下是 Windows PowerShell 示例：

```powershell
cd scripts
.venv\Scripts\python.exe main.py `
  --source "源数据包目录"
```

Windows 中文环境下如遇编码错误，先设置 `$env:PYTHONUTF8 = "1"`。

## 参数说明

- `--platform` 支持 `all`（默认）、`tmall`、`cbme`、`jd`、`vip`、`fengxiang-aikucun`、`offsite`。
- `--template` 指定模板目录，默认使用 skill 内置 `template`。
- `--output` 指定输出目录，默认 `E:\桌面\multi-platform-image-processor\output`。
- `--report` 指定报告路径，默认保存到 `scripts/output/report/`，最多保留 100 份。
- `--source` 自动检测数据源结构：
  - **单产品**：`--source` 指向 `数据包` 目录，或其父目录包含 `数据包/` 子目录，输出以 `数据包` 父文件夹名为产品名。
  - **批处理**：`--source` 指向一个包含多个产品子目录的总包（每个子目录内含 `数据包/`），自动逐个处理，输出目录以各产品的 `数据包` 父文件夹名命名。
- 站外 SKU 去文字依赖 `text2image` skill（默认模型 `gemini-3-pro-image-preview`，10 并发）。脚本识别右侧商品卡片左边缘，向左增加图片宽度 `3%` 的安全余量，将右侧纵向裁片放入与原图同尺寸的模型输入画布。模型结果必须保持输入宽高比，并通过非文字区域差异验收；最终只回贴彩色标签内部，其他区域使用原图。识别、模型或验收失败时按原图压缩输出并写入报告风险。
- **脚本完成后，Agent 必须读取报告 JSON，检查 `失败项`、`风险`、`警告`、`Agent复核建议` 字段，并向用户逐条给出警告说明。**
- **输入包检测失败时，Agent 必须读取 `输入包检测.问题` 和 `输入包检测.标准输入结构`，向用户逐条说明实际问题，并使用 Markdown 代码块完整展示报告中的标准输入结构；禁止只回复“结构不通过”或省略目录树。**

## 脚本职责

- `scripts/main.py`：总入口，调度扫描、母版生成、平台派生、质检、报告。
- `scripts/common/`：通用工具模块。
  - `utils.py`：路径、图片信息、报告管理等基础工具。
  - `image_resize_compress.py`：图片缩放、格式转换、JPG/PNG 压缩。
  - `scan_source_pack.py`：扫描源包并生成素材清单。
  - `source_pack_validator.py`：在处理前强制检查标准文件夹结构，并通过透明通道连通区域识别主体外脏点。
  - `detail_page_slice.py`：详情页缩放、拼接、切片、连续命名。
  - `transparent_image_fit.py`：透明图裁边、顶满、京东放大 4px、唯品会放大 10px、保留 alpha。
  - `logo_overlay.py`：站外白底图叠加 `logo3.png`。
  - `text_removal.py`：调用 text2image 模型生成站外 SKU 去文字图，执行尺寸与受保护区域验收，并管理临时图保留规则。
  - `sku_card_crop.py`：识别右侧商品卡片和彩色标签，生成带左侧安全余量的模型输入，并将通过验收的标签内部区域贴回原图。
  - `quality_audit.py`：自动质检。
  - `write_report.py`：输出 JSON 报告。
- `scripts/platforms/`：各平台独立处理模块。
  - `tmall.py`：生成天猫通用版母版。
  - `cbme.py`、`jd.py`、`vip.py`、`fengxiang_aikucun.py`、`offsite.py`：各平台派生。
- `scripts/write_report.py`：中文报告输出。
- `template/`：默认平台空目录模板和站外 `logo3.png`；空目录用 `.gitkeep` 占位以便 Git 提交。

## 参考资料

- 需要确认平台尺寸、命名和来源规则时，读取 `references/platform_rules.md`。
- 需要确认输出目录、报告字段和失败策略时，读取 `references/output_contract.md`。
- 需要处理详情页结构判断、SKU 去字质检等复杂视觉任务时，读取 `references/agent_visual_tasks.md`。
- 需要补充或调整验收逻辑时，读取 `references/quality_checks.md`。

## 执行原则

- 先产出天猫通用版，再派生其他平台，避免多处重复处理详情页。
- 输入包检测未通过时必须停止，不得用非标准目录猜测或降级继续生成。
- 输入包检测未通过时，最终答复必须包含报告提供的完整标准输入结构，帮助用户直接整理数据包。
- 每个平台脚本负责平台编排逻辑；通用处理能力放在共享脚本中。
- 自动处理失败时仍尽量输出最接近规则的结果，并在报告里标记 `警告`、`风险`、`失败项` 或 `Agent复核建议`。
- 模板中存在但源数据包没有素材的文件夹必须保留为空文件夹。
- 平台规则标记为空的目录保留空目录结构。
- 透明 PNG 必须通过 `pngquant` 压缩到平台大小限制内；项目依赖 `pngquant-cli` 会在 `uv run` 时提供 `pngquant.exe`。如需使用外部二进制，可设置 `PNGQUANT_BIN`。

## 重要说明

**禁止修改脚本和本文档。若出现运行问题，请通知用户联系管理员。**
