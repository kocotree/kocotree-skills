---
name: multi-platform-image-processor
description: 全自动处理单个商品图片数据包，依据产品信息 Excel 检查并修正详情页中文面料，生成天猫、京东、CBME、唯品会、蜂享家＋爱库存、站外通用版图片，以及合格证图、吊牌图、尺码图和完整质检报告。
metadata:
  version: "1.2.0"
---

# 多平台图片处理

## 输入

业务用户提供产品数据包路径。支持以下两种等价入口：

```text
产品目录
└─ 数据包

数据包
```

目录名能够唯一识别产品货号时直接使用；否则补充产品货号。产品名称用于同货号候选复核。输出位置为空时使用默认输出目录。

## 环境准备

在 `scripts/` 目录执行：

```powershell
uv sync
.venv\Scripts\python.exe init.py
```

初始化校验 Python 环境、PNG 压缩工具、业务字体、Excel 读取能力、NAS 业务目录和 BarTender。

## 执行

标准命令：

```powershell
.venv\Scripts\python.exe main.py --source "产品数据包路径"
```

公开可选参数：

- `--output`：最终输出根目录。
- `--product-code`：产品货号。
- `--product-name`：产品名称。

Agent 在执行前逐张检查详情页，完成模块分类、连体图拆分边界、面料区域和实际尺码表区域定位，将结果作为内部上下文传给脚本。业务用户只需提供产品数据包和必要的产品身份信息。

## 固定流程

1. 识别产品身份并将 NAS 路径归一为 UNC 路径。
2. 唯一匹配产品信息 Excel 与现有 BarTender 文件。
3. 依据 Excel 中文面料检查详情页，为存在差异的详情图生成临时修正版。
4. 检查详情页必需模块，按业务顺序重排并在安全边界拆分连体图。
5. 生成天猫、京东、CBME、唯品会、蜂享家＋爱库存和站外通用版图片。
6. 使用 Excel 中文面料生成 `合格证\合格证图.jpg`，并生成不附加面料的 `吊牌图\吊牌图.jpg` 和 `尺码图\尺码图.jpg`。
7. 执行平台、业务图片和面料质检，写入顶层报告、平台子报告、运行日志和逐图明细。

原始产品数据包全程只读。面料修正版仅参与平台详情页生成，任务临时目录在平台派生完成后自动清理，不进入最终交付目录。

## 规则索引

- 输入目录树：[input_structure.md](references/input_structure.md)
- 平台转换和目录规则：[platform_rules.md](references/platform_rules.md)
- 合格证图、吊牌图和尺码图：[certificate_assets.md](references/certificate_assets.md)
- 详情页面料检查与字体规则：[material_correction.md](references/material_correction.md)
- NAS、Excel 与 BarTender 匹配：[nas_and_product_sources.md](references/nas_and_product_sources.md)
- 输出目录、报告和失败策略：[output_contract.md](references/output_contract.md)
- 自动检查与完成判定：[quality_checks.md](references/quality_checks.md)
- Agent 视觉定位与复核：[agent_visual_tasks.md](references/agent_visual_tasks.md)

## 完成要求

- 产品信息 Excel 和 BarTender 文件匹配唯一。
- 详情页全部面料区域已依据 Excel 中文原文完成检查，差异项已修正。
- 六个平台目录与三张业务图片存在并通过自动检查。
- 蜂享家＋爱库存详情页单张不超过 `1MB`，其余交付图片单张不超过 `500KB`。
- Agent 已完成详情模块、站外去字、透明图、面料、尺码表和业务图片的视觉复核。
- 顶层报告和平台子报告没有未解决的失败项。

缺少 Excel、BarTender、实际尺码表或可靠视觉区域时，报告已完成结果、候选文件和具体阻塞项。
