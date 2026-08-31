# PHASE5_IOS_UI.md

# Phase 5：iOS / Apple 风格 UI 重构

## 当前稳定状态

当前版本基础功能已经稳定：

- 293 tests passed
- 0 failed
- Alembic migration 正常
- WorkflowService 正常
- Dashboard 状态统计正常
- Batch / Item 状态流转正常
- Collection Completeness 正常
- Submission Readiness 正常
- 单 Item / Batch / ZIP 导出正常
- Backup / Restore 正常
- Windows Portable 正常

本阶段只做：

**视觉风格 + 信息层级 + 交互体验**

不要重新设计业务逻辑。

---

# 1. 视觉目标

目标不是把 Windows 软件做成放大的 iPhone。

目标是：

**Apple / iOS 视觉语言 + Windows 桌面管理软件的信息密度**

重点参考：

- iOS Settings
- macOS System Settings
- Apple Notes
- Apple Reminders
- iCloud Web
- macOS Finder Sidebar

只参考：

- 色彩
- 圆角
- 层级
- 空间
- 卡片
- Sidebar
- Button
- Badge
- Sheet

不要复制 Apple 商标或系统专有素材。

---

# 2. 业务层冻结

以下模块原则上只读：

- database/
- domain/
- services/
- Alembic
- ExportService
- BackupService
- RestoreService
- WorkflowService
- CompletenessService
- SubmissionReadinessService
- AttachmentService

禁止因为 UI 美化：

- 修改数据库 Schema
- 修改状态机
- 修改完整性规则
- 修改导出规则
- 修改备份恢复
- 修改附件文件逻辑

如果 UI 确实缺少展示数据：

优先通过已有公开 Service 获取。

只能做最小 ViewModel / Adapter。

---

# 3. Apple 风格 Design Tokens

建立统一 Theme Token。

不要在各页面硬编码颜色。

建议浅色模式：

## Background

App Background:

`#F5F5F7`

Surface:

`#FFFFFF`

Secondary Surface:

`#F2F2F7`

Elevated Surface:

`#FFFFFF`

## Text

Primary:

`#1D1D1F`

Secondary:

`#6E6E73`

Tertiary:

`#8E8E93`

## Accent

Apple Blue:

`#007AFF`

Blue Hover / selected 可使用稍柔和变体。

## Semantic

Success:

`#34C759`

Warning:

`#FF9F0A`

Danger:

`#FF3B30`

## Border

`#D2D2D7`

或更轻：

`#E5E5EA`

不要定义几十种颜色。

---

# 4. 字体

Windows 中文优先。

建议 Font Family：

`Microsoft YaHei UI`

英文 fallback：

`Segoe UI`

不要要求安装 Apple SF Pro 字体。

不要随软件分发字体文件。

视觉层级建议：

Page Title:
22–24px / Semibold

Section Title:
16–18px / Semibold

Body:
13–14px

Secondary:
12–13px

Large Number:
26–32px

---

# 5. Spacing

统一使用：

4
8
12
16
20
24
32

避免无规则：

7
13
19
23

---

# 6. 圆角

Apple 风格可以比当前 UI 更柔和，但不要过度。

建议：

Cards:
12–16px

Inputs:
9–10px

Buttons:
9–10px

Small Badge:
8–10px

Pill Badge:
高度决定圆角

---

# 7. 阴影

Qt QSS 对阴影支持有限。

不要为了阴影引入复杂绘制系统。

优先：

- Surface
- Border
- 背景层级

表达层次。

如果已有简单 QGraphicsDropShadowEffect 可局部使用：

只用于极少数浮层/Dialog。

不要所有 Card 都有厚重阴影。

---

# 8. Sidebar

Sidebar 参考 macOS/iPadOS。

背景可以使用：

`#F2F2F7`

导航：

- 首页
- 报销批次
- 所有物品
- 待补材料

分组：

管理

- 模板管理
- 设置

selected 状态：

- 柔和 Accent 背景
- Apple Blue 图标/文字

不要使用传统 Qt 深蓝高亮。

Sidebar 固定宽度约：

200–220px

---

# 9. Page Header

所有主页面统一：

左侧：

标题
辅助说明

右侧：

主要操作

例如：

`报销批次`

`管理本次和历史报销批次`

右侧：

`+ 新建批次`

---

# 10. Primary Button

Primary：

Apple Blue 背景。

适用于：

- 新建
- 保存
- 导出
- 生成
- 标记已提交

Secondary：

白色/Secondary Surface + Border。

Danger：

轻红色背景或红色文字。

不要所有操作都使用蓝色实心按钮。

---

# 11. Workflow 状态

统一显示：

COLLECTING:
`收集中`

SUBMITTED:
`已提交`

REIMBURSED:
`已报销`

ARCHIVED:
`已归档`

使用柔和 Badge。

不要只显示英文 Enum。

---

# 12. Dashboard

首页目标：

用户打开软件 3 秒内知道：

1. 还有多少事情没处理；
2. 哪些已经可以提交；
3. 哪些已提交；
4. 哪些已报销；
5. 下一步具体做什么。

顶部：

`报销归档`

辅助：

`管理你的报销材料与提交进度`

统计卡：

- 待处理
- 可提交
- 已提交
- 已报销

Apple 风格紧凑 Cards。

---

# 13. Dashboard Card

示例：

待处理

`3`

`仍有材料需要处理`

可提交

`5`

`材料已经准备完成`

不要在 Card 里塞过多字段。

---

# 14. Dashboard 待处理

下面显示：

`待处理`

Item 可以用轻量 Row / Card。

例如：

树莓派 Zero 2 W

8月实验耗材

材料收集:
4 / 4

提交材料:
2 / 3

`缺少：合并支付截图`

右侧：

`>` 或打开详情。

---

# 15. Batch List

使用 Apple 风格 Grouped List。

顶部：

报销批次
+
`+ 新建批次`

显示：

- 批次名称
- 日期
- 物品数量
- 总金额
- 状态

避免传统 Excel 风格重网格。

可以保持 QTableWidget，但：

- 不显示 Grid
- 增大 Row Height
- 使用 Surface
- selected 柔和高亮

---

# 16. Batch Detail

顶部：

返回

批次名称

辅助：

`5 个物品 · ¥1,280.50`

右侧：

`+ 新增物品`

`导出`

Workflow 操作可以单独放：

`标记批次已提交`

`标记批次已报销`

不要所有按钮一字排开。

---

# 17. All Items

搜索框参考 iOS Search。

圆角浅灰：

`搜索物品、商家或订单号`

表格保持高信息密度。

状态使用 Badge。

---

# 18. Item Detail

整个软件最重要页面。

顶部：

返回

物品名称

金额

下方 metadata：

平台 · 日期

商家

订单号

所属批次

当前报销状态

---

# 19. Item Workflow

Item Detail 顶部或状态区增加明显 Workflow Card。

例如：

当前状态

`已提交`

下方：

`标记已报销`

如果 COLLECTING：

`标记已提交`

如果 Submission 不完整：

保持现有警告确认逻辑。

只美化，不改 WorkflowService。

---

# 20. Collection / Submission

使用两个并列/上下状态 Card。

## 材料收集

4 / 4

100%

`材料完整`

## 提交材料

2 / 3

`缺少合并支付截图`

不要混为一个进度。

---

# 21. Material Section

每种材料类似 Apple Settings Group。

例如：

实物照片

`必需`

2 个附件

附件 cards...

底部：

`+ 添加附件`

如果缺失：

使用 Warning 文字：

`缺少材料`

---

# 22. Attachment Card

图片：

缩略图
文件名

操作可以做成紧凑图标/文字按钮：

- 打开
- 文件夹
- 删除

PDF：

PDF icon / label
文件名

不要使用过多边框嵌套。

---

# 23. 合并支付截图

专属 Section：

`支付凭证`

来源：

订单截图
+
支付截图

↓

最终支付截图

如果已经生成：

显示最新结果。

按钮：

`重新生成`

Submission 状态自动由已有 Service 更新。

---

# 24. Workflow 操作层级

Primary workflow action：

COLLECTING:
`标记已提交`

SUBMITTED:
`标记已报销`

REIMBURSED:
`归档`

ARCHIVED:
无主要 workflow 操作。

Danger 删除操作放页面底部。

不要和 Workflow Primary Action 放一起。

---

# 25. 待补材料

显示：

`待补材料`

`还有 X 个物品需要处理`

表格重点突出：

- 缺原始材料
- 缺提交材料

例如：

树莓派

材料：
4 / 4

提交：
2 / 3

橙色 Warning:

`缺少合并支付截图`

---

# 26. Template

Template List 参考 iOS Settings Group。

例如：

普通购物

`4 项材料 · 4 项必需`

右侧：

`>`

---

# 27. Settings

设置页面可明显使用 iOS Settings 风格。

分组：

## 数据

归档目录

数据库备份

数据库恢复

## 应用

版本

未来设置可以继续加入。

每组使用 Grouped Card。

---

# 28. Dialog / Sheet

Qt 无原生 iOS Sheet。

使用统一 Modal Dialog 即可。

要求：

- 白色 Surface
- 12–16px 圆角
- 清晰标题
- 统一输入控件
- Primary button
- Cancel

删除确认：

Danger 文字。

不要模拟手机底部弹出的 Sheet。

---

# 29. 输入框

统一：

浅灰/白色 Surface

Focus:

Apple Blue border

圆角约 9px

高度：

34–38px

---

# 30. Search

Search box 使用 Secondary Surface。

placeholder：

`搜索...`

不要明显 border。

focus 后可以 Accent Border。

---

# 31. Progress

QProgressBar：

高度约 6–8px。

背景浅灰。

完成度用 Accent 或 Success。

不要显示传统 Qt progress 内部文字。

数字单独显示。

---

# 32. Empty State

例如：

暂无报销批次

`创建第一个批次开始整理报销材料`

`新建批次`

保持简洁。

不要大插画。

---

# 33. Scrollbar

可以轻度美化 Scrollbar。

窄、柔和。

不要完全隐藏，以免 Windows 用户不知道可滚动。

---

# 34. Hover

Desktop 环境保留 hover。

Apple 风格不等于移除 Windows hover。

需要：

- navigation hover
- table row hover
- button hover
- attachment hover

---

# 35. 动画

本版本不做复杂动画。

可以保留 Qt 默认状态变化。

不要引入 Animation Framework。

---

# 36. 深色模式

Phase 5 暂时只做浅色。

不要同时增加 Dark Mode。

先把浅色稳定。

---

# 37. 功能冻结

本阶段禁止：

- 新功能
- 数据库 Schema
- OCR
- 云同步
- 手机端
- MaterialType 新业务
- Export 新功能
- Backup 新功能
- 状态机修改
- 自动更新
- PyInstaller 变化

只做 UI。

---

# 开发任务

严格一次一个 Task。

---

# iOS-1：Design Tokens + Global Theme

只建立：

- 颜色 token
- 字体
- spacing
- 圆角
- Button
- Input
- Badge
- Table
- Scrollbar

不要重构具体页面。

---

# iOS-2：Sidebar

只重构 Sidebar：

- 分组
- selected
- hover
- icon
- spacing

---

# iOS-3：Dashboard

只重构 Dashboard。

---

# iOS-4：Batch List

只重构 Batch List。

---

# iOS-5：Batch Detail

只重构 Batch Detail。

包括 Workflow 批量操作的视觉。

---

# iOS-6：All Items

只重构 All Items。

---

# iOS-7：Item Detail Header + Workflow

只处理：

- Item Header
- metadata
- workflow 状态
- Collection / Submission cards

---

# iOS-8：Material / Attachment

只处理：

- Material sections
- attachment cards
- thumbnails
- PDF cards

---

# iOS-9：Merged Payment

只处理：

订单截图 + 支付截图 → 合并结果

专属区域。

---

# iOS-10：Pending Materials

只处理待补材料页面。

---

# iOS-11：Template + Settings + Dialog

只处理：

- Template
- Settings
- Dialog

---

# iOS-12：Consistency Pass

检查：

- typography
- spacing
- button
- badge
- table
- hover
- selected
- empty states

不新增功能。

---

# iOS-13：Full Regression

运行：

`pytest -q`

必须保持业务测试全部通过。

同时运行：

`alembic upgrade head`

不允许 UI 重构破坏业务。

---

# 当前任务

现在只执行：

iOS-1：Design Tokens + Global Theme。

不要提前修改页面结构。