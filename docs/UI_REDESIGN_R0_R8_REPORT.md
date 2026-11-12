# Reimbursement Manager — UI 改造结项报告（R0–R8）

> 结项日期：2026-11-11
> 范围：桌面端全部页面与自定义对话框的视觉体系改造
> 结论：**R0–R8 全部通过验收**。本轮只改 UI 层与 UI 测试，业务层零改动。

---

## 1. 最终基线

| 项目 | 数值 |
| --- | --- |
| 全量 `pytest` | **419 passed** |
| `tests/ui` | **145 passed** |
| 改造前基线 | 405 passed（R0 起点） |
| 新增测试 | 14 个（分 6 个测试文件） |
| 页面 | 8 个 |
| 自定义对话框 | 5 个（新增批次 / 新增物品 / 新增材料类型 / 模板编辑器 / 应用更新） |
| 验证尺寸 | 1100×700、1280×800、1440×900 |

---

## 2. 分阶段记录

### R0 设计令牌与基础约束

- 建立 `ThemeTokens`（颜色 / 间距 / 组件尺寸 / 字号 / 圆角），QSS 全部改为 `@TOKEN@` 占位符渲染
- 确定六档字号体系：24 / 17 / 14 / 13 / 12 / 28（指标）
- 确定间距网格：4 / 8 / 12 / 16 / 20 / 24 / 32
- **结果**：QSS 内零裸色值、零未定义令牌、零重复选择器（R8 复核仍成立）

### R1 批次列表与导航骨架

- 侧栏改为「主区 + 管理」两组导航，图标随选中态切换
- 批次列表列预算与金额右对齐
- 新增 `tests/ui/test_r1_ui_consistency.py`

### R2 图标与打包资源

- 新增 `ui/icons.py` + 12 个 18×18 SVG（每项含普通/选中两态）
- `ReimbursementManager.spec` 纳入图标资源
- 新增 `tests/ui/test_r2_navigation_icons.py`

### R3 首页工作台

- 统计卡、待处理行、进度条语义化
- 引入 `ElidedLabel`：超长文本省略绘制、`text()` 返回全文、ToolTip 恒为全文
- 首页像素差异 15.03%，其余页面 0.02%
- 新增 `tests/ui/test_r3_dashboard.py`

### R4 物品详情上半 + 批次详情主操作

- 金额由 accent 蓝改主文本色，`_format_cents` 加千分位并修正负数
- 名称 + 状态徽标 + 金额合并为一行；元信息卡改为单行文本
- 三块（状态卡 + 双进度卡 + 工作流）合并为一条状态带，高度 246px → 86px
- 批次详情两个实心 Primary 收敛为一个（工作流按钮改 quiet 变体）
- 物品详情 44.8%、批次详情 0.57% 变化，其余 6 页 0.00%
- 新增 `tests/ui/test_r4_detail_hierarchy.py`

### R5 材料区与支付凭证区

- 材料卡标题 17→14px，「必需/可选」改中性标签，附件数按已上传着色
- 附件卡 224→184px，一行 3 张变 4 张；文件名改用 `ElidedLabel` 中间省略
- 支付凭证「灰卡套灰卡 + 纵向箭头」改为三个并列槽位（来源 + 来源 → 合并结果）
- 术语统一为「合并支付截图」
- 修掉 `AttachmentFlowLayout` 未声明 `heightForWidth` 导致的宽度变化塌陷
- 新增 `tests/ui/test_r5_materials_payment.py`

### R6 待补材料页与所有物品页

- 待补材料：缺失材料列换行 + 动态行高（`SingleLineDelegate` / `WrappedCellDelegate` + 行高复核）
- 名称列宽屏自动加宽（200 → 320，手动拖拽优先）
- 所有物品：列预算重排，金额与状态按内容自适应，消除 `¥12,34…` 与 `生成凭` 截断
- 新增 `tests/ui/test_r6_tables.py`

### R7 设置页、模板管理、对话框

- 对话框统一：表单标签同行、内容区可滚动、按钮行固定、主按钮补 repolish
- 新增物品对话框 737px → 657px，并具备滚动兜底
- 设置页危险区移到末尾并改危险配色；四张卡内边距统一
- 模板列表补上「编辑 / 删除」入口与删除确认（复用既有 `delete_template`）
- 新增 `tests/ui/test_r7_dialogs_and_pages.py`

### R8 全局一致性收口

- 侧栏间距 14/18 → 16/12，宽度走令牌
- 报销批次图标改为单条内容线（原两条只差 2.2px，18px 下糊成实心块）
- 两个危险区合并为一套样式与 `dangerZoneTitle`
- 令牌与实现对齐：`table_row_height` 48→52、缩略图 160×104，删除未使用的 `control_height_small`
- 关闭所有物品表的横向滚动（消除 2px 抖动型溢出）
- 新增 `tests/ui/test_r8_consistency.py`

### 收尾：合并支付截图单一删除入口

- 凭证区结果槽只保留「打开 / 文件夹」，材料卡片保留「打开 / 文件夹 / 删除」
- 两个入口仍指向同一条 Attachment（测试比对文件名与打开动作解析到的 id）
- 从材料卡删除后，凭证区回到「尚未生成合并支付截图」，无失效引用
- 新增 `tests/ui/test_merge_delete_entry.py`

---

## 3. 修改文件清单

### 修改（5 个）

| 文件 | 说明 |
| --- | --- |
| `src/reimbursement_manager/ui/windows/main_window.py` | 全部页面与对话框的构建、渲染、交互层 |
| `src/reimbursement_manager/ui/styles/base.qss` | 全量令牌化与选择器重排 |
| `src/reimbursement_manager/ui/theme.py` | 令牌定义与校准 |
| `ReimbursementManager.spec` | 打包纳入图标资源 |
| `tests/ui/test_main_window.py` | 3 处断言随 UI 变更同步（模板操作列、合并支付删除入口、危险区标题） |

### 新增（13 个）

| 文件 | 说明 |
| --- | --- |
| `src/reimbursement_manager/ui/icons.py` | 导航图标加载 |
| `src/reimbursement_manager/ui/resources/icons/*.svg` | 12 个导航图标（6 组 × 2 态） |
| `tests/ui/test_r1_ui_consistency.py` | R1 |
| `tests/ui/test_r2_navigation_icons.py` | R2 |
| `tests/ui/test_r3_dashboard.py` | R3 |
| `tests/ui/test_r4_detail_hierarchy.py` | R4 |
| `tests/ui/test_r5_materials_payment.py` | R5 |
| `tests/ui/test_r6_tables.py` | R6 |
| `tests/ui/test_r7_dialogs_and_pages.py` | R7 |
| `tests/ui/test_r8_consistency.py` | R8 |
| `tests/ui/test_merge_delete_entry.py` | 单一删除入口 |

### 未触碰（已核验）

`src/reimbursement_manager/database/**`、`domain/**`、`services/**`、`config/**`、`utils/**`、`alembic/**`、`scripts/**` 均无改动。

---

## 4. 最终验证

- **尺寸**：8 页 × 3 尺寸全部渲染检查，脚本逐页扫描无可见横向滚动、无页面宽于容器
- **对话框**：5 个对话框在 1100×700 下均不超出窗口（新增物品 657px，其余 236–576px），超高时内容区滚动、按钮行固定
- **令牌**：QSS 零裸色值、零未定义令牌、零重复选择器；5 处 `setDefaultSectionSize(52)`、侧栏 210、缩略图尺寸均改为引用令牌
- **运行时样式**：26 处 `setProperty` 逐条核对，运行时变更均伴随 repolish
- **git**：`git diff --check` 无空白错误；改动仅限 `src/**/ui/`、`tests/ui/` 与打包 spec

---

## 5. 保留问题（均已裁决接受）

1. 中文自动换行的单字末行 —— Qt 遵循 UAX#14，汉字间任意位置可断，强制标点断行需自建布局，不做
2. SVG 内嵌色（`#6E6E73` / `#007AFF`）—— 静态资源无法引用 QSS 令牌，当前仅浅色主题，无实际影响
3. 设置页「应用」卡片仅一行版本号 —— 不强行填充内容
4. 新增物品保持单列表单 —— 不做两列布局
5. 表单校验沿用 `QMessageBox` —— 不引入内联校验交互
6. 宽屏下的填充式留白 —— 表格/卡片填满视口，不做右侧留白

---

## 6. 产物位置

- 最终截图：`.ui-preview/final/pages/{1100,1280,1440}/`（8 页 × 3 尺寸）
- 佐证截图：`.ui-preview/final/evidence/`
  - `merge-entry-after.png` —— 凭证区无删除、材料卡保留删除
  - `icon-batches-comparison.png` —— 报销批次图标三版几何对比
- 审查依据：`docs/UI_AUDIT_2026-11-05.md`、`docs/CODE_REVIEW_2026-09-18.md`
- 本报告：`docs/UI_REDESIGN_R0_R8_REPORT.md`

> `.ui-preview/` 与 `.workbuddy/` 为本地工作目录，未纳入版本控制；如需长期归档，可在后续提交前决定是否加入 `.gitignore`。

---

## 7. 后续

`main_window.py`（约 4700 行）的文件拆分属于独立工程重构任务，需重新制定模块边界、迁移顺序与回归策略，**不在本轮范围内，亦不自动启动**。
