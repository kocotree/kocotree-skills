---
name: multi-platform-image-processor
description: 全自动处理商品图片数据包并输出多平台合规图片包。用于天猫通用版、京东、CBME、唯品会、蜂享家＋爱库存、站外通用版的主图、SKU、白底图、透明图、详情页、素材图分类、缩放、压缩、去字、透明裁边、切片、质检和报告生成。
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


## 核心流程

使用 `uv + Python` 自动完成整包处理。默认流程：

1. 扫描源数据包，识别 `主图`、`SKU`、`白底图`、`透明图`、`详情`、`素材图`。
2. 先生成天猫通用版母版，尤其是 `790详情页`。
3. 从天猫母版派生 CBME、京东、唯品会、蜂享家＋爱库存、站外通用版。
4. 执行确定性处理、模型去字、尺寸转换和压缩。
5. 由 Agent 根据报告中的复核建议处理复杂视觉判断。
6. 自动检查尺寸、格式、大小、透明通道、命名连续性和平台数量限制。
7. 输出平台文件夹和中文 JSON 报告。

## 推荐命令

在本 skill 目录下运行，注意使用虚拟环境，以下是 Windows PowerShell 示例：

```powershell
cd scripts
.venv\Scripts\python.exe run_pipeline.py `
  --source "源数据包目录"
```

默认输出全平台。`--platform` 支持：`all`、`tmall`、`cbme`、`jd`、`vip`、`fengxiang-aikucun`、`offsite`。

默认模板目录为 skill 内置 `template`，可用 `--template` 指定其他模板。默认输出目录为 `E:\桌面\multi-platform-image-processor\output`，可用 `--output` 指定交付目录。如果源目录是带产品名的文件夹，例如 `KQ26019 小灵眸夹片太阳镜\数据包`，或直接传入产品文件夹 `KQ26019 小灵眸夹片太阳镜` 且其中包含 `数据包`，最终输出会保留产品名文件夹，平台目录生成在 `<输出目录>\KQ26019 小灵眸夹片太阳镜\` 内。

默认报告保存到 `scripts/output/report/<输出目录名>-<时间戳>-report.json`，供 Agent 复核使用，最多保留最近 100 份。可用 `--report` 指定报告路径。

站外 `800sku去除文字` 使用 `text2image` Agent skill 生图脚本处理，递归识别 `SKU` 多层子目录图片，默认 5 并发；默认使用 `gemini-3-pro-image-preview` 模型生成图片，最终统一输出为 `800x800` JPG。脚本优先查找本地 Agent skill 目录 `~/.codex/skills/text2image`（如果设置了 `CODEX_HOME`，则使用 `$CODEX_HOME/skills/text2image`），并会在 `~/.codex/skills` 内扫描名为 `text2image` 的 skill。若本地未找到，会从 `https://github.com/ranjingya/kocotree-skills/tree/master/skills/text2image` 安装到当前 skill 的同级目录 `text2image`，例如当前 skill 位于 `~/.codex/skills/multi-platform-image-processor` 时，安装目标为 `~/.codex/skills/text2image`；安装后继续使用该目录。调用时严格使用 `text2image/scripts/.venv/Scripts/python.exe` 执行 `main.py`，如果虚拟环境不存在，会按原图压缩输出并写入报告风险。模型临时图保存到 `scripts/output/image-without-text-tmp`，最多保留最近 100 张；模型失败时按原图压缩输出并写入报告风险。

Windows 中文环境下如遇 Python 读取 UTF-8 中文文件报编码错误，先在 PowerShell 设置：

```powershell
$env:PYTHONUTF8 = "1"
```

## 脚本职责

- `scripts/run_pipeline.py`：总入口，调度扫描、母版生成、平台派生、质检、报告。
- `scripts/scan_source_pack.py`：扫描源包并生成素材清单。
- `scripts/build_tmall_master.py`：生成天猫通用版母版。
- `scripts/derive_cbme.py`、`scripts/derive_jd.py`、`scripts/derive_vip.py`、`scripts/derive_fengxiang_aikucun.py`、`scripts/derive_offsite.py`：各平台独立派生。
- `scripts/image_resize_compress.py`：图片缩放、格式转换、JPG/PNG 压缩。
- `scripts/transparent_image_fit.py`：透明图裁边、顶满、京东放大 4px、唯品会放大 10px、保留 alpha。
- `scripts/detail_page_slice.py`：详情页缩放、拼接、切片、连续命名。
- `scripts/logo_overlay.py`：站外白底图叠加 `logo3.png`。
- `scripts/text_removal.py`：调用 text2image 模型生成站外 SKU 去文字图，并管理临时图保留规则。
- `scripts/quality_audit.py`：自动质检。
- `scripts/write_report.py`：中文报告输出。
- `template/`：默认平台空目录模板和站外 `logo3.png`；空目录用 `.gitkeep` 占位以便 Git 提交。

## 参考资料

- 需要确认平台尺寸、命名和来源规则时，读取 `references/platform_rules.md`。
- 需要确认输出目录、报告字段和失败策略时，读取 `references/output_contract.md`。
- 需要处理详情页结构判断、SKU 去字质检等复杂视觉任务时，读取 `references/agent_visual_tasks.md`。
- 需要补充或调整验收逻辑时，读取 `references/quality_checks.md`。

## 执行原则

- 先产出天猫通用版，再派生其他平台，避免多处重复处理详情页。
- 每个平台脚本负责平台编排逻辑；通用处理能力放在共享脚本中。
- 自动处理失败时仍尽量输出最接近规则的结果，并在报告里标记 `警告`、`风险`、`失败项` 或 `Agent复核建议`。
- 模板中存在但源数据包没有素材的文件夹必须保留为空文件夹。
- 平台规则标记为空的目录保留空目录结构。
- 透明 PNG 必须通过 `pngquant` 压缩到平台大小限制内；项目依赖 `pngquant-cli` 会在 `uv run` 时提供 `pngquant.exe`。如需使用外部二进制，可设置 `PNGQUANT_BIN`。
