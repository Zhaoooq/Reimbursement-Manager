# PHASE3_LEAN.md

# Phase 3：最终提交材料导出

## 当前状态

Phase 2 已完成并冻结。

回归结果：

- 169 tests passed
- 0 failed
- Alembic migration 正常
- 核心业务链正常
- Collection Completeness 正常
- Submission Readiness 正常
- 合并支付截图正常
- 附件上传、删除、打开正常
- 待补材料正常
- 模板管理正常

Phase 3 不再修改 Phase 2 已稳定的核心业务逻辑，除非发现明确阻塞问题。

---

# Phase 3 总目标

实现最终报销材料导出。

当前普通购物 Item 的原始材料包括：

- 实物照片
- 发票
- 订单截图
- 原始支付截图

其中：

订单截图 + 原始支付截图
→ 横向合并
→ 合并支付截图

最终提交时只需要：

- 实物照片
- 发票
- 合并支付截图

因此必须继续区分：

Collection Materials

和

Submission Materials

---

# 最终导出规则

对于普通购物 Item：

导出：

- 实物照片
- 发票
- 最新有效的合并支付截图

不导出：

- 原始订单截图
- 原始支付截图

本地原始归档文件全部保留。

导出操作始终是 COPY。

禁止 MOVE 原始材料。

---

# 开发方式

继续采用低额度模式。

每次只执行一个 Task。

不要一次执行整个 Phase 3。

普通任务：

只读取当前任务需要的文件。

只运行相关测试。

Phase 3 最终收尾时再运行完整：

`pytest -q`

---

# Task 13：单个 Item ExportService

状态：

已完成。

目标：

实现单个 Item 的最终提交材料导出。

当前已实现：

- `ExportService`
- Submission Readiness 检查
- 实物图导出
- 发票导出
- 最新合并支付截图导出
- 原始订单截图不导出
- 原始支付截图不导出
- 合并支付截图导出时去掉“合并”字样
- 多张实物图导出
- 多张发票导出
- 临时目录
- 成功后原子改名
- 防止覆盖已有目标目录
- 缺失文件失败
- 不改变业务状态

Task 13 已完成，不重复实现。

---

# Task 14：Item Detail 一键导出

目标：

把现有 `ExportService` 接入 Item Detail。

增加：

`导出提交材料`

用户流程：

Item Detail
→
Submission Ready
→
点击“导出提交材料”
→
选择目标目录
→
调用 ExportService
→
显示导出结果

要求：

- 使用 `QFileDialog.getExistingDirectory()`；
- UI 不自己复制文件；
- UI 不决定导出哪些附件；
- UI 不自己生成文件名；
- UI 不修改原附件；
- 用户取消选择目录时无副作用；
- ExportService 失败时 GUI 不崩溃；
- 导出成功后显示最终路径；
- 导出成功不自动修改报销状态。

Submission 未就绪时：

显示缺失提交材料，或禁用按钮。

不要重新实现 Submission Readiness。

---

# Task 15：批次导出 Service

目标：

一次导出一个报销批次下所有 Item 的最终提交材料。

例如：

用户选择：

`D:\报销导出`

批次：

`2026年8月实验耗材`

输出：

```text
D:\报销导出\
└─ 2026年8月实验耗材\
   ├─ 001_树莓派Zero2W\
   │  ├─ 001_树莓派Zero2W_实物图_01.jpg
   │  ├─ 001_树莓派Zero2W_发票_01.pdf
   │  └─ 001_树莓派Zero2W_支付截图_01.png
   │
   ├─ 002_SD卡\
   │  ├─ ...
   │
   └─ 003_HDMI转接头\
      ├─ ...
```

实现：

`export_batch(batch_id, destination_dir)`

优先复用：

`ExportService.export_item()`

或抽取内部共享逻辑。

不要重新写一套附件选择规则。

---

# Task 15.1：批次导出前检查

批次导出前必须检查所有 Item 的：

`SubmissionReadiness`

分类：

- Ready
- Not Ready

例如：

```text
树莓派 Zero 2 W
Ready

SD卡
Not Ready
缺：合并支付截图

HDMI转接头
Not Ready
缺：发票
```

默认：

如果存在 Not Ready Item：

不要直接开始正式导出。

返回结构化检查结果。

后续 UI 决定用户是否取消或强制导出。

---

# Task 15.2：批次导出一致性

批次导出必须避免半成功状态。

推荐：

```text
destination
↓
.tmp_batch_export_xxx
↓
逐个导出 Item
↓
全部成功
↓
rename
↓
正式批次目录
```

如果中途失败：

删除临时目录。

不要留下：

```text
批次目录/
├─ Item A 完整
├─ Item B 半成品
└─ Item C 不存在
```

看似正式完成的错误导出。

---

# Task 16：批次导出 UI

在 Batch Detail 增加：

`导出报销材料`

流程：

```text
点击
↓
检查 Submission Readiness
↓
全部 Ready
↓
选择目标目录
↓
导出
↓
成功提示
```

如果存在未就绪 Item：

显示：

```text
以下物品提交材料不完整：

树莓派 Zero 2 W
缺：合并支付截图

SD卡
缺：发票
```

提供：

- 取消
- 强制导出

---

# Task 17：强制导出

正常导出要求所有 Item Submission Ready。

但现实中用户可能希望：

“先导出当前已经准备好的材料”。

因此允许：

`强制导出`

规则：

对于未就绪 Item：

导出当前存在的最终提交材料。

例如：

某 Item：

- 实物图 ✅
- 发票 ✅
- 合并支付截图 ❌

强制导出后：

该 Item 目录包含：

- 实物图
- 发票

不要伪造支付截图。

不要把原始支付截图代替合并支付截图。

---

# Task 17.1：强制导出报告

强制导出后生成一个简单报告。

例如：

`导出结果.txt`

内容类似：

```text
批次：2026年8月实验耗材

以下物品提交材料不完整：

001 树莓派 Zero 2 W
缺少：
- 合并支付截图

003 HDMI转接头
缺少：
- 发票
```

报告只用于提醒用户。

不要做复杂 PDF 报告。

---

# Task 18：ZIP 导出

批次文件夹导出稳定后，再增加 ZIP。

支持：

```text
导出文件夹
```

和：

```text
导出 ZIP
```

ZIP 内容与文件夹导出完全一致。

不要重新实现一套材料选择规则。

推荐：

```text
Batch Export
↓
临时目录
↓
ZIP
↓
成功
↓
删除临时目录
```

---

# Task 19：导出命名规则

继续统一使用现有 `NamingService`。

最终提交文件名：

```text
{sequence}_{item_name}_{submission_material}_{index}.{ext}
```

例如：

```text
001_树莓派Zero2W_实物图_01.jpg
001_树莓派Zero2W_实物图_02.jpg
001_树莓派Zero2W_发票_01.pdf
001_树莓派Zero2W_支付截图_01.png
```

最终导出中禁止出现：

```text
支付截图_合并
```

应该转换为：

```text
支付截图
```

本地归档名称保持不变。

---

# Task 20：批次目录命名

批次目录使用安全文件名。

例如：

```text
2026-08_实验耗材报销
```

或当前 Batch 实际名称的安全版本。

必须复用 Windows 文件名清洗规则。

处理：

```text
< > : " / \ | ? *
```

不要重新实现一套清洗函数。

---

# Task 21：导出结果验证

导出完成后，Service 应返回结构化结果。

例如：

```python
BatchExportResult(
    path=...,
    item_count=10,
    exported_item_count=10,
    file_count=32,
    incomplete_items=[]
)
```

不要求完全使用这个类名。

目的：

让 UI 不需要重新扫描导出目录统计结果。

---

# Task 22：导出失败处理

至少处理：

- 目标目录没有权限
- 源附件不存在
- 目标目录已存在
- 临时目录创建失败
- copy 失败
- rename 失败
- ZIP 创建失败
- Batch 不存在
- Item 不存在

原则：

正式导出目录不能处于半完成状态。

GUI 不显示 Python traceback。

日志记录技术错误。

---

# Task 23：数据库备份

Phase 3 后期实现简单数据库备份。

目标：

把 SQLite 数据库复制到用户选择目录。

例如：

```text
backup/
reimbursement_2026-08-29_013000.db
```

备份前：

确保数据库事务已经提交。

优先使用 SQLite 安全 backup API。

不要直接在数据库正在写入时粗暴复制文件。

---

# Task 24：归档信息备份

数据库备份之外，可以生成简单：

`backup_info.json`

记录：

- backup_time
- app_version
- archive_root
- database_version

本任务不要复制整个附件归档。

完整附件备份属于另一个更大的功能。

---

# Task 25：Windows 打包

只有 Phase 3 功能稳定后进行。

目标：

生成 Windows 可运行版本。

优先考虑：

PyInstaller

最终用户不需要：

- Python
- VS Code
- Conda
- 手动运行脚本

即可启动软件。

先做：

portable build

再考虑 installer。

---

# Task 26：应用数据路径

Windows 打包前确认：

数据库、配置、日志不要写进：

程序安装目录。

应使用可写用户数据目录。

例如：

```text
%LOCALAPPDATA%
```

或当前项目已有合理路径策略。

附件 `archive_root` 仍由用户配置。

---

# Task 27：Phase 3 最终回归

Phase 3 所有功能完成后：

运行：

`pytest -q`

必须保证 Phase 1、Phase 2、Phase 3 测试全部通过。

---

# Phase 3 最终手工验收

创建 Batch：

```text
2026年8月实验耗材
```

其中：

```text
001 树莓派 Zero 2 W
002 SD卡
003 HDMI转接头
```

每个 Item 上传：

- 实物图
- 支付截图
- 发票
- 订单截图

生成：

- 合并支付截图

确认：

Collection = 4/4

Submission = 3/3

然后：

批次详情
→
导出报销材料
→
选择目录

最终得到：

```text
2026年8月实验耗材/
├─ 001_树莓派Zero2W/
│  ├─ 实物图
│  ├─ 发票
│  └─ 支付截图
├─ 002_SD卡/
│  ├─ 实物图
│  ├─ 发票
│  └─ 支付截图
└─ 003_HDMI转接头/
   ├─ 实物图
   ├─ 发票
   └─ 支付截图
```

最终目录中不得出现：

- 原始订单截图
- 原始支付截图
- “支付截图_合并”字样

---

# Phase 3 禁止事项

当前 Phase 3 不做：

- OCR
- AI
- 自动识别发票
- 云同步
- WebDAV
- NAS 同步
- 手机端
- Web API
- 多用户
- 登录系统
- 在线报销提交
- 自动连接财务系统
- PDF OCR
- 自动读取金额

不要因为导出功能顺便实现这些需求。

---

# 当前任务

当前 Task 13 已完成。

现在只执行：

Task 14：Item Detail 一键导出。

完成后停止。

下一步才执行：

Task 15：批次导出 Service。