# AGENTS.md

## 1. 项目目标

本项目是一个本地运行的 Windows 桌面软件，用于管理个人报销材料。

软件核心目标只有三个：

1. 明确知道每个报销物品还缺哪些材料。
2. 快速定位某个物品对应的全部报销文件。
3. 报销时能够一键得到已经分类、重命名、整理好的材料。

不要把项目设计成 ERP、财务系统或云端协作平台。

第一版必须保持：

- 单用户
- 本地运行
- Windows 优先
- 本地文件系统存储附件
- SQLite 保存结构化数据
- 不依赖云服务器

---

## 2. 核心业务模型

系统的数据关系必须围绕以下结构设计：

```text
报销批次
  └─ 报销物品
       └─ 材料要求
            └─ 实际附件
```

核心实体：

- Batch：报销批次
- Item：报销物品
- MaterialType：材料类型
- MaterialRequirement：某个物品需要哪些材料
- Attachment：实际上传的文件
- Template：报销材料模板

注意：

“文件”不是系统的一等业务对象。

“报销物品”才是一等业务对象。

系统必须能够直接回答：

```text
树莓派 Zero 2 W
材料完整度：3 / 4
缺少：发票
```

而不是让用户手动打开文件夹检查。

---

## 3. 第一版技术栈

默认使用：

```text
Python 3.12+
PySide6
SQLite
SQLAlchemy 2.x
Alembic
pytest
```

除非发现明确的技术阻塞，否则不要擅自切换：

- Electron
- Tauri
- Web 前端
- 云数据库

附件文件不要存入 SQLite BLOB。

SQLite 只保存：

- 业务数据
- 文件路径
- 文件元数据
- 文件 Hash
- 状态

实际附件必须保存为普通磁盘文件。

---

## 4. 项目架构原则

推荐结构：

```text
reimbursement-manager/
├─ AGENTS.md
├─ README.md
├─ pyproject.toml
├─ src/
│  └─ reimbursement_manager/
│     ├─ app.py
│     ├─ config/
│     ├─ database/
│     │  ├─ models/
│     │  ├─ repositories/
│     │  ├─ migrations/
│     │  └─ session.py
│     ├─ domain/
│     │  ├─ enums.py
│     │  ├─ schemas.py
│     │  └─ services/
│     ├─ services/
│     │  ├─ file_service.py
│     │  ├─ attachment_service.py
│     │  ├─ completeness_service.py
│     │  ├─ naming_service.py
│     │  └─ export_service.py
│     ├─ ui/
│     │  ├─ windows/
│     │  ├─ pages/
│     │  ├─ dialogs/
│     │  └─ widgets/
│     └─ utils/
├─ tests/
└─ data/
```

必须保持分层：

```text
UI
↓
Application / Service
↓
Repository
↓
Database
```

UI 层禁止直接写复杂 SQL。

文件系统操作禁止散落在 UI 代码中。

业务规则禁止依赖具体 Qt 控件。

---

## 5. MVP 功能边界

### P0：第一版必须实现

- 创建报销批次
- 创建报销物品
- 编辑报销物品
- 删除报销物品
- 材料模板
- 自动生成材料清单
- 上传附件
- 附件分类
- 自动重命名
- 材料完整性计算
- 缺失材料显示
- Dashboard
- 搜索和筛选
- 报销状态管理
- 打开附件
- 打开附件所在文件夹
- 批次导出

### P1：MVP 完成后再实现

- ZIP 导出
- 数据库备份
- SHA256 重复文件检测优化
- 批量添加物品
- 自定义文件命名模板

### P2：禁止第一阶段实现

- OCR
- 发票自动识别
- 微信截图识别
- 支付宝截图识别
- 云同步
- NAS 同步
- WebDAV
- OneDrive
- 多设备同步
- 手机 App
- Web 服务
- AI 自动匹配材料

不要为了未来扩展而提前实现复杂抽象。

---

## 6. 核心数据库实体

至少设计以下表。

### reimbursement_batches

建议字段：

```text
id
name
created_at
updated_at
status
reimburser
project_name
notes
submitted_at
reimbursed_at
archived_at
```

---

### items

建议字段：

```text
id
batch_id
sequence_number
name
purchase_date
merchant
platform
order_number
quantity
unit_price
total_amount
status
notes
created_at
updated_at
```

金额禁止使用 float。

推荐：

```text
Decimal
```

数据库可存：

```text
INTEGER cents
```

或精确定点类型。

---

### material_types

```text
id
name
code
description
created_at
```

例如：

```text
physical_photo
payment_screenshot
invoice
order_screenshot
order_detail
other
```

---

### material_requirements

表示：

“某个 Item 需要哪些材料”。

字段：

```text
id
item_id
material_type_id
required
sort_order
created_at
```

---

### attachments

字段至少包括：

```text
id
item_id
material_type_id
original_filename
stored_filename
relative_path
file_extension
file_size
sha256
created_at
```

优先保存相对于归档根目录的：

```text
relative_path
```

不要默认保存硬编码绝对路径。

---

### templates

```text
id
name
description
created_at
updated_at
```

---

### template_materials

```text
id
template_id
material_type_id
required
sort_order
```

---

## 7. 材料完整性规则

完整性必须由数据动态计算。

不要在数据库中维护容易失真的：

```text
completion_percentage
is_complete
missing_count
```

作为唯一真实来源。

计算逻辑：

```text
required_materials =
所有 required = true 的 MaterialRequirement

completed_materials =
存在至少一个有效 Attachment 的材料类型

missing =
required_materials - completed_materials
```

例如：

```text
必需材料：
实物照片
支付截图
发票
订单截图

已上传：
实物照片
支付截图
订单截图

结果：

completed = 3
required = 4
percentage = 75%
missing = ["发票"]
```

一个材料类型允许多个附件。

只要至少存在一个有效附件，即认为该材料类型已经满足。

后续可以扩展数量要求，但 MVP 不实现。

---

## 8. 报销状态和材料状态必须分离

禁止使用一个 status 字段同时表达：

```text
材料不完整
材料完整
已提交
已报销
```

这是两个不同维度。

### 材料状态

应该动态计算：

```text
INCOMPLETE
COMPLETE
```

### 报销流程状态

建议：

```text
COLLECTING
READY
SUBMITTED
REIMBURSED
ARCHIVED
```

其中：

READY 可以根据材料完整性自动推导，也可以作为显示状态，不一定需要持久化。

推荐业务关系：

```text
材料未完整
→ COLLECTING

材料完整
→ READY

用户确认提交
→ SUBMITTED

用户确认报销完成
→ REIMBURSED

归档
→ ARCHIVED
```

不要因为删除一个附件就自动把：

```text
SUBMITTED
```

改回：

```text
COLLECTING
```

材料完整性和报销流程状态必须独立。

---

## 9. 文件存储规则

默认归档结构：

```text
报销归档/
└─ 2026-08_实验耗材报销/
   ├─ 001_树莓派Zero2W/
   │  ├─ 001_树莓派Zero2W_实物图_01.jpg
   │  ├─ 001_树莓派Zero2W_实物图_02.jpg
   │  ├─ 001_树莓派Zero2W_支付截图_01.png
   │  └─ 001_树莓派Zero2W_发票_01.pdf
   └─ 002_SD卡/
```

默认命名格式：

```text
{sequence}_{item_name}_{material_type}_{index}.{ext}
```

示例：

```text
001_树莓派Zero2W_发票_01.pdf
```

---

## 10. 文件名清洗

Windows 文件名禁止字符：

```text
< > : " / \ | ? *
```

命名服务必须统一清洗。

必须处理：

- Windows 保留字符
- 前后空格
- 末尾句点
- 超长文件名
- Unicode 中文
- 同名冲突
- Windows 保留名称

例如：

```text
CON
PRN
AUX
NUL
COM1
LPT1
```

文件名生成逻辑必须集中在：

```text
NamingService
```

禁止多个模块自行拼接文件名。

---

## 11. 附件上传事务

附件上传属于跨：

```text
文件系统 + SQLite
```

的操作。

必须处理部分失败。

推荐流程：

```text
1. 验证源文件存在
2. 验证支持的文件类型
3. 读取文件元数据
4. 计算 SHA256
5. 检查重复
6. 生成目标目录
7. 生成安全文件名
8. 将文件复制到临时路径
9. 验证复制成功
10. 原子 rename 到正式文件
11. 开启数据库事务
12. 创建 Attachment 记录
13. commit
```

如果数据库写入失败：

尽量删除刚创建的目标文件。

如果文件复制失败：

禁止创建数据库记录。

数据库中不能出现：

```text
attachment 存在
但实际文件不存在
```

---

## 12. 默认附件策略

MVP 默认：

```text
COPY
```

即：

用户拖入一个文件后，复制到归档目录。

不要默认 MOVE 原始文件。

原因：

避免破坏用户原始：

- 下载目录
- 微信目录
- 手机导出目录
- 发票目录

未来可以提供：

```text
复制
移动
```

模式。

但默认必须复制。

---

## 13. 删除策略

删除附件时：

MVP 优先：

```text
移动到应用 Trash
```

而不是直接永久删除。

例如：

```text
报销归档/.trash/
```

删除数据库记录和文件操作需要保持一致。

后续可以接 Windows Recycle Bin。

第一版不需要为了系统回收站引入复杂依赖。

---

## 14. 文件路径原则

数据库优先保存：

```text
relative_path
```

配置中保存：

```text
archive_root
```

实际路径：

```text
archive_root / relative_path
```

这样用户迁移整个归档目录后，只需要修改：

```text
archive_root
```

而不需要修改所有 Attachment。

---

## 15. 用户手动修改文件的处理

软件必须考虑用户可能：

- 删除附件
- 修改附件名
- 移动附件
- 删除文件夹

MVP 至少实现：

访问附件前检查：

```text
Path.exists()
```

如果不存在：

显示：

```text
文件缺失
```

并将该 Attachment 标记为异常。

禁止直接程序崩溃。

后续可以开发：

```text
重新定位文件
```

MVP 可暂不实现自动修复。

---

## 16. 模板逻辑

创建一个 Item 时：

```text
选择 Template
↓
复制模板对应材料要求
↓
生成该 Item 自己的 MaterialRequirement
```

注意：

不要让 Item 永久动态依赖 Template。

模板修改后：

默认不要修改已有 Item。

否则可能出现：

```text
昨天材料完整
今天修改模板
旧物品突然全部不完整
```

模板只用于：

```text
创建时初始化
```

---

## 17. UI 信息架构

左侧导航：

```text
首页
报销批次
所有物品
待补材料
模板管理
设置
```

核心页面：

### Dashboard

显示：

```text
待整理
材料不完整
材料完整待报销
已提交
已报销
```

重点区域：

```text
待补材料
```

---

### 报销批次

展示：

```text
批次名称
物品数量
总金额
完整度
状态
创建日期
```

---

### 物品详情

顶部：

```text
物品名称
金额
购买日期
平台
订单号
材料完整度
```

主体：

按材料类型展示附件。

例如：

```text
实物照片 ✅
[图片] [图片]

支付截图 ✅
[图片]

发票 ❌
[上传]

订单截图 ✅
[图片]
```

---

## 18. Dashboard 核心逻辑

Dashboard 不应该只展示统计图。

最重要的是告诉用户：

```text
下一步该补什么材料
```

例如：

```text
树莓派 Zero 2 W
缺：发票

HDMI 转接头
缺：实物照片、支付截图

PCB 加工
缺：订单明细
```

优先实现这种信息，而不是复杂图表。

---

## 19. 搜索

MVP 至少支持：

```text
item.name
merchant
order_number
batch.name
```

筛选：

```text
材料完整
材料不完整

收集中
已提交
已报销
已归档
```

---

## 20. 导出

报销批次导出前必须运行完整性检查。

如果存在缺失：

显示：

```text
以下物品材料不完整：

树莓派 Zero 2 W
缺少：发票

HDMI 转接头
缺少：实物照片
```

提供：

```text
取消
强制导出
```

不要完全禁止用户导出。

导出不得改变原始归档目录。

建议：

```text
原归档目录
↓
复制
↓
export/
```

---

## 21. 编码要求

所有代码：

- 使用类型注解
- 保持模块职责单一
- 避免超大类
- 避免 God Object
- 避免 UI 和数据库耦合
- 避免全局可变状态
- 核心业务逻辑必须可测试
- 文件操作必须有异常处理
- SQLite 操作必须使用事务

禁止：

```text
except Exception:
    pass
```

禁止吞掉异常。

用户可恢复异常应该：

```text
记录日志
+
显示可理解错误信息
```

---

## 22. 测试要求

业务层优先写测试。

至少覆盖：

- 创建 Item
- 模板实例化
- 材料完整性判断
- 一个材料多个附件
- 删除附件后的完整性变化
- 中文文件名
- Windows 非法字符
- 同名附件
- SHA256 重复附件
- 附件复制失败
- DB 写入失败
- 文件不存在
- 相对路径计算

测试文件系统操作时使用：

```text
pytest tmp_path
```

不要污染真实用户目录。

---

## 23. Codex 工作方式

不要一次性实现整个项目。

严格遵循：

```text
分析
→
设计
→
小范围实现
→
测试
→
检查
→
下一任务
```

每次执行一个明确任务。

每个任务完成后必须说明：

```text
1. 修改了哪些文件
2. 实现了什么
3. 做了哪些设计决策
4. 测试结果
5. 当前已知问题
6. 下一步建议
```

---

## 24. 修改规则

修改现有代码前：

1. 先阅读相关模块。
2. 理解现有数据流。
3. 尽量局部修改。
4. 不为单一问题大规模重构。
5. 不擅自修改数据库模型。
6. 数据库 Schema 改动必须通过 migration。
7. 不在未说明原因的情况下新增第三方依赖。

---

## 25. 当前优先级

开发顺序固定为：

```text
数据库模型
↓
Repository
↓
文件命名
↓
文件归档
↓
附件服务
↓
完整性判断
↓
基础业务 Service
↓
UI
↓
Dashboard
↓
导出
↓
打包
```

第一阶段禁止优先开发 UI。

先确保底层模型和文件管理正确。

---

## 26. 核心设计判断标准

任何设计决策优先回答：

```text
这个设计是否让用户更容易知道：

1. 哪些材料没收齐？
2. 材料在哪里？
3. 能否直接导出报销？
```

如果答案是否定的，则该功能优先级降低。

---

## 27. 当前阶段

当前处于：

```text
Phase 1：核心数据层和文件管理基础
```

不要提前实现完整 UI。

请严格根据项目中的：

```text
PHASE1_TASKS.md
```

逐项执行。