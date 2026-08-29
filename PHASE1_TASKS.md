# PHASE1_TASKS.md

# Phase 1：核心数据层与文件管理

## 阶段目标

本阶段只建立软件的底层基础。

完成后应该能够通过自动化测试或简单 Python 调用完成：

```text
创建模板
↓
创建报销物品
↓
根据模板生成材料要求
↓
上传附件
↓
自动复制、分类、重命名
↓
计算材料完整性
↓
查询缺失材料
```

本阶段：

**不开发完整 GUI。**

---

# Task 0：初始化项目

目标：

建立可维护的 Python 项目。

完成：

- 创建 `pyproject.toml`
- 建立 `src` layout
- 配置 PySide6
- 配置 SQLAlchemy
- 配置 Alembic
- 配置 pytest
- 创建基础日志
- 创建 `.gitignore`
- 创建 README
- 创建应用配置模块

建议目录：

```text
src/reimbursement_manager/
tests/
```

验收标准：

```bash
pytest
```

可以正常运行。

执行：

```bash
python -m reimbursement_manager
```

至少不能因为包结构错误而失败。

---

# Task 1：定义 Domain Enum

创建必要枚举。

至少：

```python
class ReimbursementStatus:
    COLLECTING
    SUBMITTED
    REIMBURSED
    ARCHIVED
```

不要把：

```text
材料完整 / 不完整
```

存进这个状态。

材料完整性动态计算。

另外根据需要定义：

```text
AttachmentHealth
FileOperationMode
```

不要过度增加枚举。

验收：

- Enum 可序列化到数据库
- 单元测试覆盖

---

# Task 2：建立数据库连接层

实现：

```text
database/session.py
```

职责：

- 初始化 SQLite
- 创建 Engine
- Session Factory
- Transaction 生命周期管理

要求：

- SQLAlchemy 2.x
- 不允许 UI 直接持有全局 Session
- 提供测试数据库能力

开发数据库建议：

```text
data/app.db
```

测试：

```text
SQLite temporary database
```

---

# Task 3：实现数据库 Models

实现：

```text
ReimbursementBatch

Item

MaterialType

MaterialRequirement

Attachment

Template

TemplateMaterial
```

必须明确：

- Primary Key
- Foreign Key
- Relationship
- Cascade 策略
- Unique Constraint
- Index
- created_at
- updated_at

特别注意：

删除 Item 时如何处理 Attachment。

禁止未经设计直接使用：

```text
ON DELETE CASCADE
```

导致实际附件还存在但数据库记录被静默删除。

先明确行为，再实现。

---

# Task 4：设计并创建 Alembic Migration

完成第一版数据库 migration。

要求：

```bash
alembic upgrade head
```

能够创建全部表。

测试：

- 新数据库可成功迁移
- Migration 可重复执行
- Schema 与 Models 一致

不要依赖：

```python
Base.metadata.create_all()
```

作为正式生产数据库升级机制。

---

# Task 5：实现 Repository 层

至少实现：

```text
BatchRepository
ItemRepository
TemplateRepository
AttachmentRepository
MaterialTypeRepository
```

Repository 负责：

```text
CRUD
查询
数据库交互
```

Repository 不负责：

```text
文件复制
文件命名
完整性判断
UI
```

至少支持：

### Item

```text
create
get_by_id
list
update
delete
search
```

### Attachment

```text
create
get_by_id
list_by_item
list_by_material
delete
find_by_hash
```

---

# Task 6：初始化默认 MaterialType

第一次运行时创建：

```text
实物照片
支付截图
发票
订单截图
订单详情
其他
```

必须具有稳定内部 code。

例如：

```text
physical_photo
payment_screenshot
invoice
order_screenshot
order_detail
other
```

业务逻辑使用：

```text
code
```

而不是依赖中文显示名称。

要求初始化操作：

```text
idempotent
```

运行多次不能创建重复记录。

---

# Task 7：实现 Template Service

实现：

```text
TemplateService
```

支持：

- 创建模板
- 编辑模板
- 删除模板
- 添加材料要求
- 删除材料要求
- 标记 required

提供一个默认模板：

```text
普通购物
```

要求：

```text
实物照片 required
支付截图 required
发票 required
订单截图 required
```

---

# Task 8：实现 Item 创建逻辑

创建 Item 时：

```text
输入 Item 数据
+
选择 Template
↓
创建 Item
↓
复制 TemplateMaterial
↓
生成 MaterialRequirement
```

所有操作必须在同一个数据库事务中。

如果复制材料要求失败：

Item 创建也应该 rollback。

关键规则：

Template 修改后：

```text
已有 Item 的 MaterialRequirement 不变化
```

写测试验证。

---

# Task 9：实现 NamingService

创建：

```text
services/naming_service.py
```

职责：

生成安全目标文件名。

输入：

```text
sequence_number
item_name
material_name
file_index
extension
```

输出：

```text
001_树莓派Zero2W_发票_01.pdf
```

必须处理：

```text
< > : " / \ | ? *
```

必须处理：

```text
CON
PRN
AUX
NUL
COM1
COM2
...
LPT1
```

必须考虑：

- 空名称
- 前后空格
- 末尾 `.`
- Unicode
- 中文
- 超长名称
- 同名冲突

命名逻辑必须写完整单元测试。

---

# Task 10：实现 StoragePathService

负责构造：

```text
归档根目录
批次目录
Item 目录
附件路径
```

示例：

```text
archive_root/
2026-08_实验耗材报销/
001_树莓派Zero2W/
```

数据库 Attachment 保存：

```text
relative_path
```

禁止把：

```text
C:\Users\xxx\...
```

硬编码进数据库业务逻辑。

---

# Task 11：实现 HashService

实现 SHA256。

接口类似：

```python
calculate_sha256(path: Path) -> str
```

要求：

使用流式读取。

禁止：

```python
file.read()
```

一次性把大文件全部加载到内存。

至少测试：

- 同一个文件 hash 相同
- 不同文件 hash 不同
- 空文件
- 大文件模拟

---

# Task 12：实现 FileService

负责纯文件操作。

至少提供：

```text
copy_file
move_file
delete_file
file_exists
ensure_directory
```

默认附件导入模式：

```text
COPY
```

文件复制建议：

```text
source
↓
temporary file
↓
fsync / close
↓
atomic rename
↓
final path
```

至少避免把未完成文件直接暴露为正式附件。

---

# Task 13：实现 AttachmentService

这是 Phase 1 核心模块。

流程：

```text
add_attachment(
    item_id,
    material_type_id,
    source_path
)
```

内部执行：

```text
1. 获取 Item
2. 获取 MaterialRequirement
3. 验证文件存在
4. 计算 SHA256
5. 检查重复
6. 计算该材料现有附件数量
7. 生成文件名
8. 生成目标路径
9. 创建目录
10. 复制文件
11. 验证目标存在
12. 创建 Attachment 数据
13. commit
```

失败时：

文件系统和数据库尽量回滚到一致状态。

---

# Task 14：重复附件处理

至少实现 Item 范围的重复检测：

```text
item_id + sha256
```

如果完全相同文件再次加入相同 Item：

返回明确业务异常：

```text
DuplicateAttachmentError
```

不要再次复制。

不同 Item 是否允许相同文件：

MVP：

```text
允许
```

因为一张发票未来可能对应多个物品。

不要实现全局禁止。

---

# Task 15：实现 CompletenessService

创建：

```text
CompletenessService
```

输入：

```text
item_id
```

输出结构至少包含：

```python
{
    "required_count": 4,
    "completed_count": 3,
    "percentage": 75,
    "is_complete": False,
    "missing": [...]
}
```

规则：

required Requirement 中：

只要对应 MaterialType 存在 >= 1 个有效 Attachment：

即认为完成。

文件路径不存在的 Attachment：

不能算有效附件。

因此完整性计算需要考虑：

```text
数据库 Attachment
+
实际文件是否存在
```

---

# Task 16：实现缺失文件检测

增加：

```text
AttachmentHealth
```

建议至少：

```text
OK
MISSING
```

访问附件或执行完整性计算时：

```text
Path.exists(relative_path)
```

如果文件被用户手动删除：

系统不能崩溃。

完整性应该重新变成不完整。

---

# Task 17：实现附件删除

实现：

```text
remove_attachment
```

默认行为：

```text
文件
↓
移动至 .trash
↓
数据库删除 Attachment
```

如果 DB 操作失败：

尽可能把文件恢复。

不要默认：

```text
unlink permanent delete
```

---

# Task 18：测试完整业务链

创建集成测试。

完整模拟：

```text
创建数据库
↓
初始化默认材料
↓
创建“普通购物”模板
↓
创建 Batch
↓
创建“树莓派 Zero 2 W”
↓
模板自动生成 4 个 requirement
↓
上传实物照片
↓
上传支付截图
↓
上传订单截图
```

此时：

```text
required = 4
completed = 3
missing = 发票
complete = false
```

然后上传发票。

预期：

```text
required = 4
completed = 4
missing = []
complete = true
```

然后手动删除发票文件。

预期：

```text
required = 4
completed = 3
missing = 发票
complete = false
```

该测试是 Phase 1 的核心验收测试。

---

# Task 19：测试失败场景

必须覆盖至少：

## 文件系统

```text
源文件不存在
目标目录无权限
同名文件
中文路径
Windows 非法字符
文件被外部删除
```

## 数据库

模拟：

```text
文件复制完成
但数据库写入失败
```

检查：

不要残留错误正式附件。

---

# Task 20：提供开发调试入口

Phase 1 完成后提供一个简单：

```text
CLI
或
dev script
```

不用开发完整 GUI。

能够执行：

```text
创建测试 Batch
创建 Item
上传附件
查看完整度
```

例如：

```bash
python scripts/demo_phase1.py
```

输出类似：

```text
Item:
树莓派 Zero 2 W

Required:
4

Completed:
3

Missing:
- 发票

Completeness:
75%
```

用于快速验证底层功能。

---

# Phase 1 完成条件

只有以下条件全部满足才能进入 UI 开发：

## 数据库

- Schema 稳定
- Migration 正常
- Repository 正常

## 模板

- 可以创建模板
- 可以实例化到 Item

## 文件

- 可以复制附件
- 可以自动命名
- 可以生成目录
- 中文正常
- 同名正常
- 失败可恢复

## 完整性

- 能自动计算
- 能显示缺失材料
- 外部删除文件后能发现异常

## 测试

```bash
pytest
```

全部通过。

---

# Phase 1 禁止事项

本阶段不要：

- 做漂亮 UI
- 做 Dashboard
- 做 OCR
- 做云同步
- 做手机端
- 做登录系统
- 做账号系统
- 做权限系统
- 做 Web API
- 做 Docker
- 做在线服务器
- 做复杂插件架构
- 做 AI
- 做发票解析

这些都不是当前阶段的阻塞项。

---

# Codex 执行规则

不要一次执行 Task 0 到 Task 20。

按照：

```text
一次 1～3 个强相关 Task
```

推进。

每轮完成后输出：

```text
Completed
- ...

Files changed
- ...

Tests
- ...

Design decisions
- ...

Known issues
- ...

Recommended next task
- ...
```

如果发现当前任务与 AGENTS.md 存在设计冲突：

先停止扩大修改范围。

明确说明冲突：

```text
当前设计
vs
AGENTS.md 要求
```

然后选择对整体架构影响最小的方案。

数据库 Schema、文件路径策略、状态模型属于高影响决策，不得随意修改。