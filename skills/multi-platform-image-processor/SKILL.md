---
name: multi-platform-image-processor
description: 全自动处理商品图片数据包并输出多平台合规图片包与业务图片。用于完整全平台处理，制作合格证图、吊牌图、尺码图，依据产品信息 Excel 检查和修正详情页中文面料，以及从原始包、人工处理包或多平台成品包派生天猫、京东、CBME、唯品会、蜂享家＋爱库存和站外通用版图片。
---

# 多平台图片处理

## 运行模式

通过 `scripts/main.py --mode` 选择流程：

- `full`：核对并修正面料，生成六平台图片和业务图片，执行完整交付质检。
- `certificate`：生成合格证图、吊牌图和尺码图，不运行平台派生。
- `material`：检查并修正详情页面料；成品包输出修改副本。
- `platform`：运行六平台图片处理引擎，兼容平台专项任务。

完整读取模式与输入要求时使用 [workflow_modes.md](references/workflow_modes.md)。

## 环境准备

在 `scripts/` 目录初始化环境：

```powershell
uv sync
.venv\Scripts\python.exe init.py
```

初始化会校验 Python 环境、图片压缩工具、业务字体、Excel 读取能力和 BarTender 可用性。站外 SKU 去字使用 `text2image` Skill；首次调用时按认证提示完成授权。

## 推荐命令

完整流程：

```powershell
.venv\Scripts\python.exe main.py `
  --mode full `
  --source "产品数据包路径" `
  --product-code "产品货号" `
  --product-name "产品名称" `
  --include-certificate-assets
```

专项流程：

```powershell
.venv\Scripts\python.exe main.py --mode certificate --source "产品路径" --product-code "产品货号"
.venv\Scripts\python.exe main.py --mode material --source "产品路径" --product-code "产品货号"
.venv\Scripts\python.exe main.py --mode platform --source "数据包路径" --platform all
```

常用参数：

- `--source`：数据包、产品目录、批处理总目录或多平台成品包。
- `--output`：最终输出根目录。
- `--report`：报告文件路径。
- `--product-code`、`--product-name`：产品身份信息。
- `--include-certificate-assets`：完整流程生成固定三张业务图片。
- `--include-certificate-fabric`：合格证图加入 Excel 中文面料。
- `--nas-root`、`--product-info-root`、`--certificate-root`：覆盖业务资料路径。
- `--platform`：`all`、`tmall`、`cbme`、`jd`、`vip`、`fengxiang-aikucun` 或 `offsite`。
- `--template`：平台模板目录。

## 完整流程

按以下顺序执行 `full`：

1. 解析产品身份、源路径和输出路径，将映射盘符归一为 UNC 路径。
2. 匹配唯一产品信息 Excel 和 BarTender 文件，并创建本地临时源副本。
3. 读取 Excel 中文面料，检查并修正详情页母版。
4. 运行六平台处理引擎并读取平台子报告。
5. 提取实际尺码表，始终生成 `尺码图\尺码图.jpg`。
6. 触发业务图片时生成合格证图、吊牌图和尺码图。
7. 执行业务级质检并写入完整流程报告。

## 参考资料

- 识别模式、输入包类型和完成条件：读取 [workflow_modes.md](references/workflow_modes.md)。
- 处理平台图片：读取 [platform_rules.md](references/platform_rules.md)。
- 生成合格证图、吊牌图或尺码图：读取 [certificate_assets.md](references/certificate_assets.md)。
- 检查或修正面料：读取 [material_correction.md](references/material_correction.md)。
- 访问 NAS、Excel 或 BarTender 文件：读取 [nas_and_product_sources.md](references/nas_and_product_sources.md)。
- 确认输出目录和报告字段：读取 [output_contract.md](references/output_contract.md)。
- 执行自动与业务质检：读取 [quality_checks.md](references/quality_checks.md)。
- 处理视觉定位和复核：读取 [agent_visual_tasks.md](references/agent_visual_tasks.md)。

## 完成要求

- 所需产品资料匹配唯一，面料检查已完成。
- 平台子报告和完整流程报告中没有未解决的失败项。
- 完整流程的尺码图存在且通过质检；触发业务图片时三张图片全部通过质检。
- 报告中的警告、风险和 Agent 复核建议逐项反馈给用户。
- 遇到缺失资料、候选冲突或视觉任务无法可靠自动完成时，保留已完成结果并明确报告阻塞项。
