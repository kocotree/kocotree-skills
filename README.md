# KOCOTREE SKILLS

kocotree skills 合集

## 安装方式

告诉 Agent 工具（ Codex 等）

> 帮我安装这个skill `https://github.com/ranjingya/kocotree-skills/tree/master/skills/<skill名>`  

`<skill名>` 换成想安装的那个skill名  

> 如：帮我安装这个skill `https://github.com/ranjingya/kocotree-skills/tree/master/skills/storage-analyzer`

## 说明文档  
[KOCOTREE SKILLS 引导](https://kocotree.feishu.cn/wiki/VVVYwc2LIirFi7kEOX7chht7nIe)

## Skills 目录

| Skill | 说明 | 备注 | 需要认证 | 来源 |
|-------|------|------|:------:|------|
| [find-skills](skills/find-skills/) | 发现并推荐可安装的 Agent Skill | 依赖 `npx skills` / skills.sh | ❌ | [vercel-labs skills](https://github.com/vercel-labs/skills/tree/main/skills/find-skills) |
| [jushuitan-inventory-query](skills/jushuitan-inventory-query/) | 聚水潭库存简单查询 |    | ✅ |  鸭腿开发  |
| [text2image](skills/text2image/) | 文/图生图 | 模型：nano-banana-2、nano-banana-pro | ✅ | 鸭腿开发 |
| [storage-analyzer](skills/storage-analyzer/) | 磁盘存储分析与清理建议（交互式 HTML 报告） |  不要完全信任ai给的建议  | ❌ | [khazix-skills](https://github.com/KKKKhazix/khazix-skills/tree/main/storage-analyzer) |
| [hv-analysis](skills/hv-analysis/) | 横纵分析法深度研究（纵向追历程 + 横向比竞品，输出 PDF 报告） |    | ❌ | [khazix-skills](https://github.com/KKKKhazix/khazix-skills/tree/main/hv-analysis) |
| [multi-platform-image-processor](skills/multi-platform-image-processor/) | 全自动处理商品图片数据包并输出多平台合规图片包（天猫、京东、CBME、唯品会、蜂享家＋爱库存、站外） | 支持批处理，依赖 text2image 去字 | ✅ | 花菜、鸭腿开发 |
| [visual-detail-image-processor](skills/visual-detail-image-processor/) | 批量生成 790px 商品详情页模块（产品信息、透明图、尺码图、模特图） | 基于 2000px 模板渲染，支持批处理和 AI 模特图选框 | ❌ | 花菜、鸭腿开发 |
| [sku-image-processor](skills/sku-image-processor/) | 生成服装类 1440×1440 SKU 模板图（模特图、透明商品图、颜色名） | 支持批处理、YOLO 骨架辅助、裁切标注校验和背景补齐 | ✅ | 花菜、鸭腿开发 |
