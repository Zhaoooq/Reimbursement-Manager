# PHASE4_RELEASE.md

# Phase 4：备份与 Windows 发布

## 当前状态

Phase 1～3.5 已完成并冻结。

当前完整回归：

- 232 tests passed
- 0 failed
- Alembic migration 正常
- 应用启动正常
- UI / UX 重构完成
- 单 Item / Batch / ZIP 导出正常
- 安全删除正常
- Collection / Submission 正常

本阶段目标：

1. 数据库备份
2. 基础恢复能力
3. Windows 用户数据目录整理
4. PyInstaller 打包
5. Portable Windows 版本
6. 最终发布回归

---

# Task 1：SQLite 安全备份 Service

实现数据库备份。

要求：

- 使用 SQLite Backup API；
- 不直接在数据库活动状态下粗暴复制 `.db` 文件；
- 用户选择备份目录；
- 文件名包含时间戳；
- 中文路径正常。

例如：

`reimbursement_backup_2026-08-29_143000.db`

备份不得修改当前数据库。

只实现 Service + tests。

不要做 UI。

---

# Task 2：备份元信息

与数据库备份一起生成：

`backup_info.json`

记录：

- backup_time
- app_version
- archive_root
- database_schema_version
- database_filename

使用 UTF-8 JSON。

不要复制附件归档。

---

# Task 3：备份 UI

在“设置”页面增加：

`备份数据库`

流程：

设置
→ 备份数据库
→ 选择目录
→ BackupService
→ 成功提示

显示：

- 备份路径
- 时间

失败时 GUI 不崩溃。

---

# Task 4：恢复数据库设计

先实现基础恢复流程。

要求：

- 用户选择 `.db`
- 验证是否为有效 SQLite 数据库
- 检查必要表是否存在
- 备份当前数据库
- 替换数据库
- 重启应用后生效

恢复属于高风险操作。

必须二次确认。

不要直接覆盖而没有当前数据库备份。

---

# Task 5：Windows 用户数据目录

正式打包前检查：

数据库、配置、日志不能放在程序安装目录。

Windows 建议：

`%LOCALAPPDATA%\ReimbursementManager\`

例如：

```text
%LOCALAPPDATA%\ReimbursementManager\
├─ data\
│  └─ app.db
├─ logs\
├─ config\
└─ backups\
```

附件归档：

继续使用用户配置的 `archive_root`。

不要自动迁移用户已有归档。

---

# Task 6：配置路径迁移

如果当前开发环境仍使用：

`project/data/app.db`

需要设计一次最小迁移。

开发模式可以继续支持项目本地数据目录。

打包模式使用 LocalAppData。

不要破坏测试临时数据库。

---

# Task 7：应用版本

增加统一版本号来源。

例如：

`__version__ = "0.1.0"`

不要在多个文件重复写版本号。

未来：

- backup_info
- About
- 打包文件名

都读取同一个版本来源。

---

# Task 8：PyInstaller 基础打包

使用 PyInstaller。

优先生成：

`onedir`

Portable 版本。

第一阶段不要急着 `onefile`。

原因：

- 启动更稳定
- 资源文件更容易处理
- PySide6 打包问题更容易调试

需要包含：

- PySide6
- QSS
- SVG / icons
- Alembic migration
- 必要资源

---

# Task 9：PyInstaller Spec

建立稳定 `.spec`。

例如：

`reimbursement_manager.spec`

确保：

- styles 被打包
- migration 文件被打包
- 图标资源被打包
- 不依赖开发机器绝对路径

不要把：

`C:\Users\THIS PC\...`

写进 spec。

---

# Task 10：Portable Build

生成：

```text
dist/
└─ ReimbursementManager/
   ├─ ReimbursementManager.exe
   └─ ...
```

要求：

目标 Windows 机器无需安装：

- Python
- VS Code
- pytest

即可运行。

---

# Task 11：打包后数据库初始化

全新环境首次启动：

- 自动创建用户数据目录
- 创建 SQLite 数据库
- 执行 Alembic migration
- 初始化默认 MaterialType
- 初始化默认“普通购物”模板

不能要求用户手动运行：

`alembic upgrade head`

---

# Task 12：打包后资源验证

验证：

- QSS 正常
- Sidebar 图标正常
- 中文正常
- 缩略图正常
- PDF 卡片正常
- Dialog 正常

如果资源路径使用相对路径：

必须兼容：

- development
- PyInstaller frozen

不要在 UI 到处判断 `_MEIPASS`。

最好集中封装资源路径。

---

# Task 13：Portable 数据安全

删除 exe / 程序目录：

不能导致数据库和报销附件一起丢失。

因为：

- database 在 LocalAppData
- attachments 在 archive_root

程序文件与用户数据分离。

---

# Task 14：Windows 手工验收

在构建后的 exe 中执行：

1. 首次启动
2. 创建 Batch
3. 创建 Item
4. 上传 JPG / PNG / PDF
5. 生成合并支付截图
6. 查看缩略图
7. Collection 4/4
8. Submission 3/3
9. 单 Item 导出
10. Batch 导出
11. ZIP 导出
12. 删除 Item
13. 删除空 Batch
14. 备份数据库
15. 关闭软件
16. 重新打开
17. 数据仍存在

---

# Task 15：最终回归

开发环境运行：

`pytest -q`

必须全部通过。

打包环境进行 Smoke Test。

---

# Task 16：发布目录

最终可以生成：

```text
release/
└─ ReimbursementManager-0.1.0-win64/
```

包含：

- Portable 程序
- README.txt

README 只需要：

- 如何启动
- 数据保存位置
- 附件归档位置
- 如何备份

---

# Phase 4 暂时不做

不要：

- 在线自动更新
- 安装器
- Windows Store
- 数字签名
- 云备份
- OneDrive
- WebDAV
- NAS
- 多设备同步
- OCR
- AI

先做稳定 Portable 版本。

---

# 当前任务

现在只执行 Task 1：

SQLite 安全备份 Service。

完成后停止。