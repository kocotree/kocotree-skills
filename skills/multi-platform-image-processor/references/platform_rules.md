# 平台规则

## 通用输入目录

脚本按以下目录名识别源素材，目录不存在时记录缺失并继续处理：

- `主图\800`
- `主图\1440`
- `主图\750`
- `SKU`
- `SKU\800`
- `SKU\1440`
- `白底图`
- `透明图`
- `详情\静态`
- `详情\静态\上`
- `详情\静态\下`
- `素材图`

## 天猫通用版

- `主图\800主图`：来源 `主图\800`，输出 JPG，单张小于 `500KB`。
- `主图\750 1000主图`：来源 `主图\750`，保持 `750x1000` 类型主图，输出 JPG，单张小于 `500KB`。
- `sku\800`：来源 `SKU` 里的 800 图，输出 JPG，单张小于 `500KB`。
- `sku\1440`：有 1440 SKU 就复制压缩，没有则保持空。
- `800白底图`：来源 `白底图`，直接复制或压缩，单张小于 `500KB`。
- `800透明图`：来源 `透明图`，保持 PNG 和透明通道，使用 `pngquant` 压缩，单张小于 `500KB`。
- `790详情页`：来源 `详情\静态`，或 `详情\静态\上` + `详情\静态\下`；宽度 `790px`，单张高度小于 `1600px`，单张小于 `500KB`，命名从 `601.jpg` 连续递增。
- `素材图`：来源有 `素材图` 时原样复制，没有则保持空。

## CBME

- `750主图`：优先用 `主图\1440` 缩到 `750x750`；没有 1440 时用 `主图\800`。来源排除 `750x1000` 主图。输出 JPG，单张小于 `500KB`。
- `750详情页`：由天猫 `790详情页` 等比例缩小到 `750px` 宽，单张高度小于 `1600px`，单张小于 `500KB`，命名从 `601.jpg` 连续递增。
- 模板文件夹没有素材时保持空文件夹。

## 蜂享家＋爱库存

- `800主图`：来源 `主图\800`，输出 JPG，单张小于 `500KB`。
- `800sku`：来源 `SKU` 里的 800 图，输出 JPG，单张小于 `500KB`。
- `800白底图`：来源 `白底图`，保持视觉白底，单张小于 `500KB`。
- `790详情页`：来源详情页与天猫同一套内容，但需要重新合成长切片；宽度 `790px`，单张高度小于 `4800px`，数量小于等于 `20` 张，单张小于 `1MB`，命名为 `详情图-01.jpg`、`详情图-02.jpg`。
- `尺码图`：按模板结构保留空目录；当前脚本不主动生成内容。
- 详情页长切片不得主动切碎完整模块；自动脚本按已有详情页切片边界优先合并，超高单图才切分并记录风险。

## 京东

- `800主图`：来源 `主图\800`，输出 JPG，单张小于 `500KB`。
- `750主图`：来源 `主图\750`，保持 `750x1000` 类型主图，输出 JPG，单张小于 `500KB`。
- `800sku`：按模板结构保留空目录；当前脚本不主动生成内容。
- `750sku`：按模板结构保留空目录；当前脚本不主动生成内容。
- `透明图`：来源 `透明图`，输出 `800x800 PNG`；裁掉透明空边和半透明虚边，主体等比例放入 800 画布，上下或左右其中一边顶满，顶满后按比例额外放大 `4px`，允许轻微边缘裁切，保留透明通道，使用 `pngquant` 压缩，单张小于 `500KB`。
- `详情页`：直接复制天猫 `790详情页`，宽 `790px`，单张高度小于 `1600px`，单张小于 `500KB`，命名从 `601.jpg` 连续递增。

## 唯品会

- `1200主图`：优先用 `主图\1440` 缩到 `1200x1200`；没有 1440 时用 800 放大到 `1200x1200`。输出 JPG，单张小于 `500KB`。
- `1200透明图`：来源 `透明图` 里的 800 透明图，输出 PNG，保留透明通道；先提取主体，等比例缩放到 `1200x1200` 工作图，再按产品透明边裁切成 `某高度x1200` 或 `1200x某宽度`，最后将具体产品额外放大 `10px` 并放回裁切画布；最终输出必须有且只有一边为 `1200px`，使用 `pngquant` 压缩，单张小于 `500KB`。
- `750详情页`：由天猫 `790详情页` 等比例缩小到 `750px` 宽，单张高度小于 `1600px`，单张小于 `500KB`，命名从 `601.jpg` 连续递增。

## 站外通用版

- `800sku去除文字`：来源 `SKU` 里的 800 图，处理范围限定为右侧产品卡片上彩色装饰条（顶部圆角色块、底部弧形色块）内的文字；装饰条本身的颜色、形状、圆角、弧度保持不变；产品图、人物、衣服印花、织标、背景保持不变。没有装饰条或没有文字时原样复制压缩。输出 JPG，单张小于 `500KB`。
  - Agent 审核去字结果时，若效果不理想（误删元素、残留、变形、多加元素等），可直接使用安装时捆绑的 `text2image` skill 对问题图片单独重新生成，根据具体产品特征自行调整提示词。脚本使用的默认提示词供参考：
    ```
    Edit the image with minimal changes. Only edit the right-side white product card area. Remove only the text on that card, including text inside colored decorative labels, product name text, and any other descriptive text. The colored decorative labels may be red, green, or other colors, including top rounded color blocks and bottom curved color blocks. Strictly preserve the colored decorative labels themselves: keep their color, shape, size, position, rounded corners, curved edges, shadows, and borders unchanged. Only fill the removed text areas naturally with the same label color. Do not add, keep, or generate any numbers, numbered circles, badges, small icons, symbols, labels, or extra decorations. The right-side white product card should remain clean except for the original product photo and the preserved colored decorative labels. Keep all other content strictly unchanged, including the left-side person, clothing, fabric labels, clothing logos, clothing patterns, prints, product images, background, material textures, lighting, and overall composition. Do not add any new text, logos, graphics, borders, or objects.
    ```
- `800白底图`：来源 `白底图`，直接复制或压缩，单张小于 `500KB`。
- `800白底图＋logo`：来源 `白底图`，叠加模板里的 `logo3.png`，logo 位置和大小不二次调整，输出 JPG，单张小于 `500KB`。
- `800透明图`：来源 `透明图`，保持 PNG 和透明通道，使用 `pngquant` 压缩，单张小于 `500KB`。
- `素材图`：来源有 `素材图` 时原样复制，没有则保持空。
- `790详情页去除文字`：保留空目录。
- `800主图去除文字和边框`：保留空目录。
