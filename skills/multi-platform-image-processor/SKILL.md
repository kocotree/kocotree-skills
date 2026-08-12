---
name: multi-platform-image-processor
description: 全自动处理单个商品图片数据包，依据产品信息 Excel 检查并修正详情页中文面料，生成天猫、京东、CBME、唯品会、蜂享家＋爱库存、站外通用版图片，以及合格证图、吊牌图和尺码图，并完成内部质检。
metadata:
  version: "1.2.0"
---

# 多平台图片处理

## 输入

业务用户提供产品数据包路径。目录名能够唯一识别产品货号时直接使用；否则补充产品货号。产品名称用于同货号候选复核。

## 环境准备

在 `scripts/` 目录执行：

```powershell
uv sync
.venv\Scripts\python.exe init.py
```

## 执行

```powershell
.venv\Scripts\python.exe main.py --source "产品数据包路径"
```

公开可选参数：

- `--output`：最终输出根目录。
- `--product-code`：产品货号。
- `--product-name`：产品名称。

Agent 在执行前生成内部视觉上下文，业务用户无需提供视觉定位参数。

## 固定流程

1. 识别产品身份并解析 NAS 业务路径。
2. 唯一匹配产品信息 Excel 与 BarTender 文件。
3. 依据 Excel 中文面料检查和修正详情页。
4. 检查详情页模块，排序并拆分连体图。
5. 生成六平台图片。
6. 生成合格证图、吊牌图和尺码图。
7. 执行自动检查和 Agent 视觉复核。
8. 输出完整产品交付目录，在 Codex 页面说明处理结果。

原始产品数据包只读。任务临时文件、报告、逐图明细和日志保存在 Skill 内部，产品交付目录只包含业务产物。

## 规则索引

- 输入目录树：[input_structure.md](references/input_structure.md)
- 六平台转换规则：[platform_rules.md](references/platform_rules.md)
- NAS、Excel、面料、BarTender 和业务图片：[business_rules.md](references/business_rules.md)
- Agent 视觉定位与复核：[visual_review.md](references/visual_review.md)
- 交付目录、内部报告和完成状态：[output_contract.md](references/output_contract.md)

## 完成要求

- Excel 和 BarTender 匹配唯一。
- 详情页面料与 Excel 中文原文一致。
- 六平台目录与三张业务图片完整。
- 图片尺寸、格式、透明通道、文件大小和命名符合规则。
- Agent 完成详情模块、站外去字、透明图、面料、尺码表和业务图片复核。
- 内部完整报告没有未解决失败项。
