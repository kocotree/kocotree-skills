---
name: sku-image-processor
description: SKU 图片处理器 skill：用于服装类目 1440x1440 SKU 图片模板流程，基于模板、模特图、透明商品图和颜色名，生成最终图、标注检查图和裁切检查图。
metadata:
  version: 1.1.0
---

# SKU 图片处理器（sku-image-processor）

## 定位

本 skill 负责服装类目 `1440x1440` SKU 图片生成。脚本负责确定性预处理、标注校验、渲染合成和固定输出结构；agent 或视觉模型负责最终视觉标注。

执行顺序固定为：

```text
prep -> annotate -> validate-annotation -> render -> review
```

## 环境

- 所有需要项目依赖的 Python 命令都必须在 `scripts/` 目录使用 `uv run python ...` 执行，不使用系统默认 `python`。
- 首次同步依赖使用 `scripts/uv.lock`，执行 `uv sync --python 3.12 --frozen`，确保依赖版本与项目锁文件一致。
```bash
cd scripts
uv sync --python 3.12 --frozen
```
- **必须**在使用该skill前完成认证，命令如下。否则`render` 阶段调用带认证的生成模型会出错。禁止跳过认证。
```bash
uv run python -c "from core.auth import ensure_token; ensure_token(); print('认证可用')"
```
- 随后使用目录下的 `main.py` 执行各阶段命令：
```bash
uv run python main.py ...
```


## 输入结构

支持总目录输入：

```text
<input-root>/
  模板.png                 # 可选，存在时优先使用
  <商品目录>/
    模特图/
      <颜色名>.jpg|jpeg|png
    透明图/
      <颜色名>.png
    场景图/                # 仅透明抠像模特图需要
```

也支持单商品目录输入：

```text
<商品目录>/
  模特图/
    <颜色名>.jpg|jpeg|png
  透明图/
    <颜色名>.png
  场景图/                  # 仅透明抠像模特图需要
```

匹配规则：`模特图/` 与 `透明图/` 通过文件名（不含扩展名）匹配颜色。

## 固定输出

默认输出只保留三类图片和两个控制文件：

```text
scripts/output/<YYYYMMDD-HHMMSS>_<输入目录名>/
  final/
    <商品目录>/<颜色名>.jpg|png
  work/
    annotations.json
    summary.json
    annotated/
      _template_regions.jpg
      _final_contact_sheet.jpg
      <商品目录>/
        <颜色名>_grid.jpg
        <颜色名>_skeleton.jpg
        <颜色名>_fill_input.jpg
        <颜色名>_fill_result.jpg
    crops/
      <商品目录>/<颜色名>_crop.jpg
```

约定：

- `final/`：最终可交付图片。
- `work/annotated/`：模板参考线、网格、骨架、源图裁切框、生图补齐输入/结果和成品拼接示例等标注检查图片。
- `work/crops/`：按最终 `crop_box` 得到的裁切检查图片，越界时包含生成模型补齐的背景。
- `work/annotations.json`：标注清单，agent 或视觉模型在这里填写坐标。
- `work/summary.json`：各阶段摘要、校验结果、失败项和关键路径。

内部批次固定写入 `scripts/output/`。`render` 必须提供 `--output <目录>`，脚本把 `final/` 中的最终图片复制到该交付目录；过程文件始终保留在批次 `work/` 中。

agent 必须在渲染前确定一个不存在或为空的交付目录。任务结束时只向用户展示交付目录和最终图片，不展示批次目录、`work/` 路径或内部检查图；`work/` 仅供 agent 验收与排错。

`scripts/output/` 最多保留 50 个批次。每次 `prep` 成功后按批次时间删除最早目录，直到批次数量恢复为 50；本轮新建批次始终保留。

## 流程分工

`prep` 由脚本自动执行：

- 扫描素材、匹配颜色、判定 `opaque|transparent|no_model`。
- 读取模板和 layout 配置。
- 生成 `annotations.json` 空标注骨架。
- 生成模板参考线、坐标网格和 YOLO 骨架标注图片。

`annotate` 由脚本汇总任务，由 agent 或视觉模型填写：

- 查看 `work/annotated/` 下的模板参考线、网格图和骨架图。
- 在 `work/annotations.json` 中填写 `crop_box`。
- 构图以 `body_box.top` 距顶部约 `120px`、`crop_box` 下边界位于髋点至 `garment_box` 下限区间约 `60%` 的位置、人物关键区域完整、人物在左侧视觉居中、右侧商品贴片完整无遮挡为准；`garment_box` 不能直接作为裁切框。
- YOLO 输出只作参考，不能直接替代最终视觉判断。

`validate-annotation` 由脚本自动执行：

- 校验 `crop_box` 坐标格式、方形和源图重叠区域。
- 结果写入 `work/summary.json`。

`render` 由脚本自动执行：

- 按标注裁切模特图，越界时补齐背景，并按模板配置自动生成右侧商品贴片与颜色名。
- 生图 API 临时失败时先跳过该图继续处理批次，全部图片处理完后等待并重试一次；仍失败则在 `work/summary.json` 标记并告知用户。
- 输出 `final/`、叠加红色裁切框的 `work/annotated/*_skeleton.jpg`、`work/annotated/*_fill_input.jpg`、`work/annotated/*_fill_result.jpg`、`work/annotated/_final_contact_sheet.jpg` 和 `work/crops/*_crop.jpg`。
- 必须通过 `--output` 只导出 `final/` 中的图片，并把导出状态写入 `work/summary.json`。
- `pass` 输出最终图，`fail` 只保留检查图和摘要。

`review` 由脚本汇总，由 agent 复查：

- 从 `work/summary.json` 汇总失败项。
- agent 根据 `work/annotated/` 和 `work/crops/` 修正标注后重新校验与渲染。

## 必读规则

- 流程总览：[`references/01-流程总览.md`](references/01-流程总览.md)
- 素材匹配：[`references/02-素材匹配.md`](references/02-素材匹配.md)
- 标注与验收：[`references/03-标注与验收.md`](references/03-标注与验收.md)
- `crop_box` 构图：[`references/04-crop_box构图.md`](references/04-crop_box构图.md)
- 骨架辅助：[`references/05-骨架辅助.md`](references/05-骨架辅助.md)

## annotations.json

```json
{
  "template": "<模板路径>",
  "products": {
    "<商品名>": {
      "<颜色名>": {
        "bg_class": "opaque|transparent|no_model",
        "scene_image": "<透明模特图的场景图路径>",
        "source_image": "<模特图路径>",
        "source_size": [宽, 高],
        "annotation": {
          "crop_box": [x1, y1, x2, y2]
        }
      }
    }
  }
}
```

`crop_box` 为源图像素坐标，必须是方形，可以越出源图边界，但必须与源图有重叠区域。

## 运行

```powershell
cd scripts
uv run python main.py prep --input-root "<input-root>"
uv run python main.py annotate --annotations "output\<批次>\work\annotations.json"
uv run python main.py validate-annotation --annotations "output\<批次>\work\annotations.json"
uv run python main.py render `
  --input-root "<input-root>" `
  --annotations "output\<批次>\work\annotations.json" `
  --output "<交付目录>"
uv run python main.py review --annotations "output\<批次>\work\annotations.json"
```

常用参数：

- `prep --template-file`：指定模板。
- `prep --pose-model-name` / `--pose-confidence`：调整 YOLO 骨架模型与阈值，默认权重路径为 `scripts/models/yolo11n-pose.pt`。
- `prep --skip-pose`：仅在排查依赖或模型问题时跳过骨架辅助。
- `render --font-file`：指定颜色标签字体。

## 脚本索引

```text
scripts/main.py                    # CLI 入口
scripts/core/output_layout.py      # 固定输出结构
scripts/pipeline/prep.py           # prep 编排
scripts/annotation/tasks.py        # annotate 任务摘要
scripts/annotation/check.py        # validate-annotation 校验
scripts/pipeline/render.py         # render 编排
scripts/annotation/review.py       # review 复查摘要
scripts/pose/                      # prep 内部使用的 YOLO 骨架辅助能力
scripts/core/annotations.py        # 标注骨架、加载与基础校验
scripts/model/place.py             # 按标注裁切放置模特图
scripts/product/product_render.py  # 透明商品图与颜色标签
scripts/template/template.py       # 模板清理和参考线
scripts/qa/grid.py                 # 坐标网格图
scripts/qa/preview.py              # 标注画框图
scripts/qa/validation.py           # render 验收
```

# 注意
禁止未经用户确认，私自修改skill的任何代码和配置，所有修改必须经过严格测试和验证，并确保不会影响现有功能和用户体验。
