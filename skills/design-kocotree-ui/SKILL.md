---
name: design-kocotree-ui
description: 为 Kocotree Skills 及其他 Kocotree Web、React、Tauri 桌面软件设计、实现或审查统一 UI。用于新建页面与组件、重构现有界面、建立设计令牌、检查视觉一致性、替换第三方组件库样式，以及处理按钮、表单、下拉框、卡片、模态框、状态反馈、响应式和无障碍细节。
---

# Kocotree UI 设计

## 开始工作

1. 完整阅读 [references/design-system.md](references/design-system.md)，以其中的令牌与组件规则为准。
2. 检查现有页面结构、交互状态、响应式断点和用户已确认的视觉习惯。
3. 明确页面的单一任务、主要操作和信息密度，再决定布局与组件组合。
4. 需要查看完整效果或复用静态原型时，使用 [assets/playground/](assets/playground/) 中的 HTML、CSS 与 JavaScript。

## 工作流程

### 1. 建立页面结构

- 保留白色工作面、浅灰分区和细边框的桌面工具风格。
- 先确定导航、页面标题、内容分区和主操作，再处理装饰细节。
- 让页面结构表达信息层级，不用无意义编号、渐变或大面积品牌图形填充空间。

### 2. 应用设计令牌

- 默认使用 VI 标准绿 `#009139` 作为主交互色。
- 仅在明确需要降低长时间使用的视觉强度时，整体切换为柔和交互绿 `#2F8F68`；同一页面不要把两者作为并列主色。
- 使用 4px 间距基数、6/8/12px 圆角层级和系统 UI 字体栈。
- 普通可读文字不低于 `11px`，控件文字使用 `13px`，正文使用 `12–14px`。
- 使用墨黑承载标题，灰阶承载正文和次要信息，辅助色只表达明确状态。

### 3. 设计与实现组件

- 优先编写项目内组件和样式，不新增或扩大 Semi Design 等第三方 UI 组件库的使用，除非用户明确要求。
- 为每个组件实现默认、Hover、Focus、Active、Disabled、Loading 和错误状态中适用的部分。
- 保持操作命名一致：按钮写什么，成功或失败反馈就沿用同一动词。
- 自定义下拉框必须包含清晰的收起态、选项说明、选中标记、键盘操作、点击外部关闭和 `Esc` 关闭。
- Tooltip 同时支持鼠标悬停和键盘 Focus，使用 `role="tooltip"` 与 `aria-describedby` 建立关联，并自动避开视口边缘。

### 4. 控制品牌表达

- 让品牌绿主要出现在主按钮、选中状态、焦点和小面积识别元素。
- 圆形树冠与 60° 切角只用于低强度的空状态、引导页或微型识别细节。
- 不在页面页头、主工作区或普通卡片中放置大型绿色云朵或树冠装饰。
- 不把包装、工牌和实体宣传物料的密集纹样直接搬进软件界面。

### 5. 验证

- 在常用宽屏和最小支持宽度下检查溢出、跳变、遮挡和滚动边界。
- 使用键盘完成主要操作，确认 Focus 可见、弹层可关闭、状态不只依赖颜色。
- 检查同一区域只有一个主按钮，卡片 Hover 不被相邻容器裁切。
- 运行项目构建、类型检查和现有测试；能截图时进行视觉检查。

## 资源

- [references/design-system.md](references/design-system.md)：权威设计令牌、布局、组件、交互和验收规范。
- [assets/playground/index.html](assets/playground/index.html)：可直接运行的组件 Playground 页面。
- [assets/playground/styles.css](assets/playground/styles.css)：完整设计令牌和组件样式示例。
- [assets/playground/app.js](assets/playground/app.js)：Tooltip、下拉框、模态框、Toast、密度和配色切换的交互示例。
