---
name: visual-detail-image-processor
description: 详情页图片处理批量生成 skill：使用用户提供的 2000px 详情页模板、商品素材目录和结构化商品数据，批量输出 790px JPG 模块。适用于替换/生成 产品信息、透明图、选尺码、尺码快选、模特图，或需要把图片表格识别结果固定为 product_data.json 后稳定批量渲染的场景。
---

# 视觉详情页模板生成

## 环境准备

首次使用前需在skill的 `scripts/` 目录下初始化 Python 环境：

```bash
cd scripts
uv sync
```

如未安装 uv，先执行：

- macOS/Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- Windows: `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`

初始化完成后，务必使用 `.venv` 中的 Python 执行工具脚本。


## 输入结构

商品素材结构通常为：

```text
<input-root>/
  <product-folder>/
    product_data.json
    产品信息.jpg|png
    选尺码.png|jpg|jpeg
    尺码快选.png|jpg|jpeg
    透明图/
      <颜色名>.png
    模特图/
      1.jpg
      2.jpg
      3.jpg
```

内置模板目录为：

```text
template/
```

模板结构通常为：

```text
template/
  01产品信息.jpg
  02透明图.jpg
  03选尺码.jpg
  04推荐尺码.jpg
  05尺码快选.jpg
  模特图1.jpg
  模特图2.jpg
  模特图2覆盖.png
  模特图3.jpg
```

## 执行流程

1. 先确认输入根目录和输出根目录；默认使用 skill 内置 `template/` 和 `assets/`。
2. 若商品还没有结构化数据，先使用 GPT 本身的图像识别能力读取 `产品信息`、`选尺码`、`尺码快选` 三张图，按商品合并生成 JSON，并保存到 `scripts/output/product_data/<商品文件夹名>-product_data-<时间戳>.json`。
3. 读取 [图片表格转数据规则](references/04-图片表格转数据规则.md)，校验商品 JSON，不确定内容写入 `warnings`，不能编造。
4. 在运行渲染脚本前，先扫描商品是否存在模特图素材；只要存在可读取的模特图，就必须先使用 AI 审美选图/选框，为每张可用模特图输出源图原始像素坐标，并保存到 `scripts/output/visual_model_selection/visual_model_selection-<时间戳>.json`。
5. 运行通用批处理脚本，不允许写死商品名或商品数据；如果本轮生成了 AI 坐标 JSON，必须显式传入 `--visual-model-selection "<坐标json路径>"`，不能依赖脚本自动回退或自动等待数据。
6. 对每个商品分别生成输出子文件夹，子文件夹名保留原商品文件夹名。
7. 成品图片只输出到 `--output-root/<商品文件夹名>/`；批处理报告统一输出到 `scripts/output/report/render_report-<时间戳>.json`。
8. 输出后做视觉与尺寸检查，尤其检查白框、绿线残留、表格残影、文字错位、透明图大小跳动和模特图裁切。
9. 读取报告确认所有有坐标的模特图 `mode` 为 `visual_model_selection`；若回退 `cover_crop`，必须逐条说明是坐标缺失、坐标无效、源文件不存在，还是当前环境无法可靠视觉判断。

## 必读细则

根据任务读取对应 reference：

- 处理任意批量任务前，读取 [批量执行规则](references/01-批量执行规则.md)。
- 需要了解固定字体资源时，读取 [内置资源规则](references/02-内置资源规则.md)。
- 需要了解或替换模板资源时，读取 [内置模板资源规则](references/03-内置模板资源规则.md)。
- 需要从图片/表格素材得到数据时，读取 [图片表格转数据规则](references/04-图片表格转数据规则.md)。
- 绘制文字或遇到字体问题时，读取 [字体与文字规则](references/05-字体与文字规则.md)。
- 处理 `01产品信息.jpg` 时，读取 [产品信息规则](references/06-产品信息规则.md)。
- 处理 `02透明图.jpg` 时，读取 [透明图规则](references/07-透明图规则.md)。
- 处理 `03选尺码.jpg` 或 `05尺码快选.jpg` 时，读取 [表格规则](references/08-表格规则.md)。
- 处理 `模特图1.jpg`、`模特图2.jpg`、`模特图3.jpg` 时，读取 [模特图规则](references/09-模特图规则.md)。
- 需要使用 AI 主观审美裁切坐标时，读取 [智能模特图选框规则](references/10-智能模特图选框规则.md)。
- 使用或维护脚本时，读取 [脚本说明](references/11-脚本说明.md)。

## 当前脚本

```text
scripts/detail_template_replacer_2000.py
scripts/main.py
scripts/create_product_data_template.py
scripts/validate_product_data.py
```

## 运行

示例命令：

```powershell
cd scripts
uv run python main.py `
  --input-root "<input-root>" `
  --output-root "<output-root>"
```

如果本轮存在模特图素材，先生成 `visual_model_selection-<时间戳>.json`，再显式传入坐标文件：

```powershell
cd scripts
uv run python main.py `
  --input-root "<input-root>" `
  --output-root "<output-root>" `
  --visual-model-selection "output/visual_model_selection/visual_model_selection-<时间戳>.json"
```

如果使用外部数据目录或外部模板目录：

```powershell
cd scripts
uv run python main.py `
  --input-root "<input-root>" `
  --output-root "<output-root>" `
  --data-dir "<data-dir>" `
  --template-dir "<custom-template-dir>" `
  --visual-model-selection "<visual_model_selection-json>"
```

## 验收底线

- 每个输入商品文件夹都必须被处理或被报告原因。
- 所有输出图片宽度必须为 790px。
- 模板固定文字、背景、绿色块、logo、装饰线、覆盖层不能被动态绘制破坏。
- 商品数据必须来自 `product_data.json` 或等价结构化文件，不能写死在 Python 里。
- 空值留空，不补默认值，不推算。
- 不能出现白框、绿线残留、表格残影、绿色表头白竖线。
- 同类文字字号和粗细一致，混排数字不能上下乱跳。
- 透明图同页商品视觉大小一致，颜色名贴近商品且同一基线。
- 模特图主体不变形，优先保证头部完整和主体完整。
- 含模特图素材的批处理必须先产出 AI 坐标 JSON 再运行脚本；报告中对应模特图应显示 `visual_model_selection`，除非已明确说明无法使用 AI 坐标的原因。
