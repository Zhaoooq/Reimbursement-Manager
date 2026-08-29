# PHASE3_5_UI.md

# Phase 3.5：UI / UX 重构

## 当前状态

Phase 1～3 核心功能已经稳定。

当前完整回归：

- 202 tests passed
- 0 failed
- Alembic migration 正常
- 单 Item 导出正常
- Batch 导出正常
- 强制导出正常
- ZIP 导出正常
- Collection Completeness 正常
- Submission Readiness 正常
- 合并支付截图正常

本阶段目标：

**只提升界面视觉质量、信息层级和操作效率。**

不要重新设计业务逻辑。

---

# 1. 核心原则

UI 重构必须遵循：

```text
业务正确性
>
操作效率
>
信息层级
>
视觉效果
>
动画
```

不要为了“漂亮”降低信息密度。

这是一个：

“个人报销材料管理桌面工具”

不是展示型网站。

---

# 2. 业务层冻结

以下目录原则上只读：

```text
database/
domain/
services/
```

除非：

UI 存在明确阻塞，且无法通过 UI Adapter / ViewModel / DTO 解决。

禁止因为 UI 重构：

- 修改数据库 Schema
- 修改 MaterialRequirement 规则
- 修改 CompletenessService
- 修改 SubmissionReadinessService
- 修改 ExportService 业务规则
- 修改附件文件结构
- 修改模板业务规则
- 重写 Phase 1～3 Service

如果认为必须修改业务层：

停止扩大修改范围，并说明原因。

---

# 3. 允许重点修改

主要修改：

```text
ui/
resources/
styles/
```

可根据项目结构增加：

```text
ui/theme.py
ui/styles/
ui/widgets/
ui/icons/
```

不要建立复杂前端式设计系统。

---

# 4. 整体视觉目标

目标风格：

- 现代桌面管理软件
- 简洁
- 高信息密度
- 清晰层级
- 轻量
- 专业
- Windows 友好

参考方向：

- Linear
- Notion
- GitHub Desktop
- VS Code Settings
- 现代 SaaS Dashboard

不是要求复制这些产品。

只参考：

- 信息层级
- spacing
- Sidebar
- Card
- Table
- Badge
- 状态反馈

---

# 5. 不要做的视觉风格

避免：

- 大面积渐变
- 高饱和配色
- 毛玻璃滥用
- 大量圆角
- 巨大标题
- 大面积留白
- 卡片套卡片
- 复杂动画
- 拟物风格
- 游戏 UI
- 手机 App 风格
- Web 页面感过重

---

# 6. 全局布局

主窗口建议：

```text
┌──────────────────────────────────────────────────────┐
│ Sidebar        │ Page                                │
│                │                                     │
│ 报销归档        │ 页面标题                            │
│                │ 页面说明 / Actions                  │
│ 首页            │                                     │
│ 报销批次        │ 内容区域                            │
│ 所有物品        │                                     │
│ 待补材料        │                                     │
│ 模板管理        │                                     │
│ 设置            │                                     │
│                │                                     │
└──────────────────────────────────────────────────────┘
```

保持固定 Sidebar。

主内容区域自适应。

---

# 7. Sidebar

改造当前左侧导航。

包含：

- 首页
- 报销批次
- 所有物品
- 待补材料
- 模板管理
- 设置

要求：

- 图标 + 中文标题
- 当前页面明显高亮
- hover 状态
- selected 状态
- 统一高度
- 统一 padding
- Sidebar 固定宽度
- 不使用巨大图标

顶部：

`报销归档`

可以增加简单应用图标，但不是必要条件。

---

# 8. 全局字体和尺寸

Windows 中文优先。

不要硬编码非常特殊字体。

优先使用系统可用中文字体，例如：

- Microsoft YaHei UI
- Segoe UI
- 系统默认字体

建议视觉层级：

```text
页面标题：
20～24 px

区域标题：
15～18 px

正文：
13～14 px

辅助信息：
12～13 px
```

不要使用过多字号。

---

# 9. Spacing

建立统一 spacing。

建议基本单位：

```text
4
8
12
16
24
32
```

不要到处出现：

```text
7px
13px
19px
```

这种无规则间距。

---

# 10. 圆角

轻度圆角即可。

例如：

```text
6px
8px
```

不要所有控件使用巨大：

```text
16px
24px
```

---

# 11. Button

统一按钮层级。

至少区分：

## Primary

主要操作：

- 新增物品
- 新建批次
- 导出提交材料
- 生成合并支付截图

## Secondary

普通操作：

- 编辑
- 打开
- 打开文件夹

## Danger

危险操作：

- 删除附件

危险按钮不要过度突出。

---

# 12. Badge

建立统一状态 Badge。

例如：

```text
[ 材料完整 ]
[ 缺材料 ]
[ 可提交 ]
[ 已提交 ]
[ 已报销 ]
[ 已归档 ]
```

Badge 只用于状态。

不要把普通文字全部做成 Badge。

---

# 13. Table

所有表格统一风格。

适用于：

- Batch 列表
- Item 列表
- 待补材料
- Template 列表

要求：

- 表头明确
- 行高适中
- hover
- selected
- 数字右对齐
- 金额右对齐
- 文本省略策略合理
- 缺失材料列可读

避免传统灰色 Qt 默认表格视觉。

---

# 14. Dashboard

首页重构为真正工作台。

顶部：

```text
报销概览
```

下方统计：

```text
┌──────────────┐
│ 待补材料   3 │
└──────────────┘

┌──────────────┐
│ 可提交     5 │
└──────────────┘

┌──────────────┐
│ 已提交     8 │
└──────────────┘

┌──────────────┐
│ 已报销    12 │
└──────────────┘
```

统计卡保持紧凑。

不要做巨大 Dashboard。

---

# 15. Dashboard 待处理区域

首页重点仍然是：

“下一步需要处理什么？”

例如：

```text
待处理

树莓派 Zero 2 W
2026年8月实验耗材

材料收集   4/4
提交材料   2/3

缺：合并支付截图
```

另外：

```text
HDMI 转接头

材料收集   3/4
缺：发票
```

优先突出：

- Item 名称
- 缺什么
- 当前进度

不要优先做统计图。

---

# 16. Batch 列表

批次列表顶部：

```text
报销批次                         [ + 新建批次 ]
```

表格显示：

- 名称
- 创建日期
- Item 数量
- 总金额
- 状态

空状态：

```text
暂无报销批次

创建一个批次开始整理报销材料。

[ 新建批次 ]
```

---

# 17. Batch Detail

页面顶部：

```text
← 报销批次

2026年8月实验耗材
5 个物品 · ¥1280.50
```

右侧操作：

```text
[ 新增物品 ]
[ 导出报销材料 ]
```

下面：

- 批次概览
- Item 表格

不要堆很多卡片。

---

# 18. All Items

顶部：

```text
所有物品

[搜索物品 / 商家 / 订单号]
```

表格：

- 物品
- 批次
- 金额
- 日期
- 平台
- 材料
- 缺失
- 状态

材料：

```text
3 / 4
```

缺失：

```text
发票
```

或者：

```text
材料完整
```

---

# 19. Item Detail

这是整个应用最重要页面。

重点重构。

顶部建议：

```text
← 所有物品

树莓派 Zero 2 W                  ¥180.00

淘宝 · 2026-08-20
订单号：XXXXXXXX
所属批次：2026年8月实验耗材
```

---

# 20. Item Detail 状态区域

清晰分开：

```text
材料收集

4 / 4
████████████████████
材料完整
```

以及：

```text
提交材料

2 / 3
█████████████░░░░░░░
缺：合并支付截图
```

禁止重新计算。

继续读取：

- CompletenessService
- SubmissionReadinessService

---

# 21. Item Detail 材料区域

不要再简单显示一大串 Label。

每种材料做成统一 Material Section。

例如：

```text
✓ 实物照片                               2 个附件

photo_01.jpg
[打开] [所在文件夹] [删除]

photo_02.jpg
[打开] [所在文件夹] [删除]

                                     [ + 添加附件 ]
```

材料之间保持清晰分隔。

---

# 22. 图片缩略图

本阶段可以正式加入图片缩略图。

支持：

- JPG
- JPEG
- PNG

实物照片、订单截图、支付截图优先显示缩略图。

建议：

固定缩略图容器尺寸。

保持比例。

不要裁剪原图重要信息。

可以使用：

`QPixmap.scaled(..., KeepAspectRatio, SmoothTransformation)`

不要为了缩略图增加 Pillow 依赖，除非当前项目已经依赖。

---

# 23. PDF

PDF 第一版：

不要做完整 PDF 内嵌预览。

显示：

- PDF 图标
- 文件名
- 文件大小（如果现有数据方便获得）

点击：

打开。

避免为 UI 阶段引入 PDF 渲染依赖。

---

# 24. 合并支付截图区域

Item Detail 中单独增加：

```text
合并支付截图
```

显示：

```text
订单截图       支付截图

[缩略图]   +   [缩略图]

        ↓

合并支付截图

[            缩略图            ]
```

操作：

```text
[ 生成合并支付截图 ]
```

如果已经存在：

```text
[ 重新生成 ]
```

不要修改现有合并业务逻辑。

---

# 25. 导出区域

Submission Ready：

```text
提交材料已完整

[ 导出提交材料 ]
```

Submission Not Ready：

```text
提交材料未完整
缺：合并支付截图

[ 导出提交材料 ] disabled
```

保持现有业务规则。

---

# 26. 待补材料页面

页面标题：

```text
待补材料
```

顶部可以显示：

```text
还有 4 个物品需要处理
```

表格至少显示：

- 物品
- 批次
- 原始材料
- 缺失
- 提交材料
- 缺失提交材料

缺失内容应该是视觉重点。

---

# 27. 模板管理

列表：

```text
模板管理                         [ + 新建模板 ]

普通购物
4 项材料 · 4 项必需

加工服务
5 项材料 · 4 项必需
```

编辑 Dialog：

保持简单。

不要为了漂亮改 Template 业务。

---

# 28. Dialog

统一所有 Dialog：

- 新建批次
- 新建 Item
- 编辑模板
- 导出选择
- 删除确认

要求：

- 标题统一
- 字段间距统一
- Primary / Cancel 按钮位置统一
- 必填项清楚
- 错误提示位置统一

---

# 29. Empty State

统一 Empty State。

不要只是：

`暂无数据`

最好：

```text
暂无物品

创建第一个报销物品后，
它会出现在这里。

[ 新增物品 ]
```

但保持简洁。

---

# 30. Error / Success

不要到处使用不同格式。

统一：

成功：
简洁通知。

失败：
简洁说明 + 可恢复建议。

例如：

```text
附件上传失败
目标文件无法写入。
```

不要显示 traceback。

---

# 31. QSS

建立统一 QSS。

例如：

```text
ui/styles/
    base.qss
```

或：

```text
resources/styles.qss
```

不要每个 Widget：

```python
setStyleSheet(...)
```

写一套自己的样式。

少量动态状态可以例外。

---

# 32. 颜色

使用有限颜色体系。

至少：

- Background
- Surface
- Border
- Text Primary
- Text Secondary
- Accent
- Success
- Warning
- Danger

不要定义几十种颜色。

---

# 33. 深色模式

本 Phase 暂时不做。

先把浅色模式做好。

不要因为 Theme System 增加复杂度。

深色模式以后再做。

---

# 34. 图标

可以使用：

- Qt 内置图标
- 简单 SVG 资源

优先保持依赖最少。

不要为了几个导航图标引入巨大 icon library。

所有图标大小保持统一。

---

# 35. Responsiveness

目标窗口：

最低支持约：

```text
1100 × 700
```

主要内容区域可随窗口扩大。

不要假设固定 1920×1080。

表格和详情页应合理伸缩。

---

# 36. Scroll

Item Detail 内容可能很多。

必须使用合理 ScrollArea。

不能因为附件多导致窗口无限变高。

---

# 37. 性能

缩略图不能阻塞整个应用太久。

MVP：

只加载当前 Item Detail 所需图片。

不要启动时扫描所有图片。

不要建立复杂 thumbnail cache，除非实际发现性能问题。

---

# 38. 无障碍基本要求

至少保证：

- 按钮文本明确
- 不只依靠颜色表达状态
- Warning 同时有文字
- 字号不要过小
- Disabled 状态仍可辨识

---

# 39. UI 测试原则

不要因为 UI 重构重写大量脆弱像素测试。

继续测试：

- Widget 存在
- 关键文本
- 按钮状态
- 页面导航
- Service 调用

不要测试：

- 精确 pixel
- QSS 每个数值
- 控件绝对坐标

---

# 40. 开发顺序

严格按以下小任务推进。

---

# Task UI-1：全局 Theme + Sidebar

只做：

- 全局 QSS
- Sidebar
- 导航按钮状态
- MainWindow 基础 spacing
- 页面容器基础样式

不要改 Dashboard 内容。

---

# Task UI-2：Dashboard

只重构首页。

包括：

- 统计卡
- 待处理区域
- 信息层级

不要动其他页面。

---

# Task UI-3：Batch List

只重构：

- Batch 列表
- 新建批次 Dialog

---

# Task UI-4：Batch Detail

只重构：

- Batch Detail
- Item Table
- 导出按钮区域
- 新增 Item 入口

---

# Task UI-5：All Items

只重构：

- 搜索框
- Item Table
- Badge
- Empty State

---

# Task UI-6：Item Detail 基础

只重构：

- 顶部信息
- Collection / Submission 状态
- Material Section 布局

暂时不加缩略图。

---

# Task UI-7：附件缩略图

只增加：

- JPG/JPEG/PNG 缩略图
- PDF 文件卡片

不要做图片查看器。

---

# Task UI-8：合并支付截图 UI

只美化：

- 原订单截图
- 原支付截图
- 合并结果
- 生成 / 重新生成按钮

不改合并算法。

---

# Task UI-9：待补材料

只重构：

- 待补材料页面
- 状态显示
- 缺失材料视觉层级

---

# Task UI-10：模板管理 + Dialog

统一：

- Template 页面
- 新建/编辑模板 Dialog
- 其他主要 Dialog spacing

---

# Task UI-11：统一细节

最后统一：

- Button
- Badge
- Table
- Empty State
- Error / Success
- spacing
- font
- alignment

不要加新功能。

---

# Task UI-12：完整回归

完成 UI 重构后：

`pytest -q`

必须保证：

Phase 1～3 所有业务测试仍通过。

---

# UI 阶段禁止事项

不要：

- 修改数据库 Schema
- OCR
- AI
- 云同步
- 手机端
- Web API
- 多用户
- 深色模式
- 自动更新
- Windows installer
- 重写业务 Service
- 改导出业务规则
- 改完整性规则

本阶段只做：

UI / UX。