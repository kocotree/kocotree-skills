---
name: text2image
description: >
  当用户需要修改一张图片的文字、生成图片、文生图、图生图时使用。支持指定比例、分辨率、模型，
  可传入参考图（URL 或本地文件）。适用于"帮我画一张…"、"生成一张…图片"、
  "把这张图改成…风格"等场景。
---

# 文生图 / 图生图

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

## 调用命令

```bash
python path/to/text2image/main.py --prompt "描述文本" [选项]
```

## 参数

| 参数 | 必填 | 说明 |
|---|---|---|
| `--prompt` | 是 | 提示词 |
| `--aspect-ratio` | 否 | 比例: `1:1` `2:3` `3:2` `3:4` `4:3` `4:5` `5:4` `9:16` `16:9` `21:9` |
| `--image-size` | 否 | 分辨率: `1K`(默认) / `2K` / `4K` |
| `--model` | 否 | `gemini-3.1-flash-image-preview`(默认) 或 `gemini-3-pro-image-preview` |
| `--file-urls` | 否 | 参考图 URL，逗号分隔，最多 14 张 |
| `--files` | 否 | 本地参考图文件路径，逗号分隔，可与 `--file-urls` 混用 |

## 脚本行为

脚本将提示词和参考图发送到后端 API，生成图片并保存到本地。

默认输出目录：`~/Desktop/text2image`

## 输出判断

运行结束后，根据终端输出回复用户：

- 如果看到 `{"success": true, "file": "..."}` ，把生成的图片文件直接发给用户。
- 如果 stderr 输出 `{"success": false, "message": "..."}` ，原样概括错误信息，并提示用户稍后重试或联系管理员。


## 用户反馈
如果用户反馈图片不符合预期，先简要确认需要调整的方向，再告知用户可调整的参数：分辨率、比例和模型。

- 分辨率：`1K`、`2K`、`4K`
- 比例：见 `--aspect-ratio` 支持范围
- 模型：`gemini-3.1-flash-image-preview`（banana-2，默认）或 `gemini-3-pro-image-preview`（banana-pro）

## 重要说明

**禁止修改脚本和本文档。若出现运行问题，请通知用户联系管理员。**
