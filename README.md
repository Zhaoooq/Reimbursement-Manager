# 报销材料管理器

ReimbursementManager 是一个 Windows 优先、单用户、本地运行的报销材料管理工具。它围绕“报销批次 → 报销物品 → 材料要求 → 实际附件”组织资料，帮助你确认材料是否齐全、快速定位文件，并导出整理好的报销材料。

当前稳定版本：**v0.2.2**

## 主要功能

- 创建、编辑和删除报销批次与报销物品。
- 使用材料模板初始化物品所需材料；模板变更不会影响已有物品。
- 点击选择或直接拖入一个或多个附件，并复制到独立的附件归档目录。
- 自动安全重命名附件，处理 Windows 非法字符、保留名称和同名冲突。
- 动态显示材料完整度和缺失材料；收集完整度与提交就绪状态分开计算。
- 合并支付截图，打开附件或所在文件夹，并将删除的附件移入归档目录中的 `.trash`。
- 提供 Dashboard、批次、全部物品、待补材料、模板管理和设置页面；支持按名称、商家、订单号和批次搜索。
- 导出单个物品、完整批次或批次 ZIP；材料不完整时可取消或明确选择强制导出，并生成说明文件。
- 通过“设置”页面备份和恢复 SQLite 数据库；恢复前会先创建安全备份。
- 在“设置 → 应用更新”中检查并安装新版本：下载发布包、校验 SHA-256、重启后替换程序目录，数据库与附件不受影响。

## 使用 Portable 发布版

打开发布目录中的 `ReimbursementManager.exe` 即可启动，无需安装 Python 或开发环境。

程序与用户数据相互独立：

- 数据库：`%LOCALAPPDATA%\ReimbursementManager\data\app.db`
- 日志：`%LOCALAPPDATA%\ReimbursementManager\logs\`
- 配置与数据库备份：`%LOCALAPPDATA%\ReimbursementManager\config\`、`%LOCALAPPDATA%\ReimbursementManager\backups\`
- 报销附件：保存在软件配置的附件归档目录，不保存在程序目录中。

删除或移动 Portable 程序目录不会自动删除数据库和附件归档；反过来，复制程序目录也不等于备份全部业务数据。

### 备份与恢复

“设置”页面可备份或恢复数据库。数据库备份不包含 JPG、PNG、PDF 等附件；如需完整保留报销资料，请同时备份：

1. 数据库备份文件；
2. 实际附件归档目录。

恢复数据库会替换当前数据库，软件会先执行安全备份；恢复操作不会复制或恢复附件文件。

## 本地开发

### 环境要求

- Python 3.12+
- Windows 10/11

### 安装依赖

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

### 启动应用

```powershell
python -m reimbursement_manager
```

开发模式的运行数据位于项目内的 `data/` 目录：

```text
data/
├─ app.db
├─ archive/
├─ backups/
├─ config/
└─ logs/
```

这些目录均属于本地用户数据，已被 Git 忽略。

### 数据库迁移

应用启动时会自动执行迁移。开发时如需手动升级或检查版本，可使用：

```powershell
alembic upgrade head
alembic current
```

正式 Schema 仅通过 Alembic migration 维护，不依赖 `Base.metadata.create_all()`。

### 测试

```powershell
python -m pytest
```

在无图形环境中运行 PySide6 测试时：

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
python -m pytest
```

## 构建发布版

先生成 PyInstaller `onedir` 构建：

```powershell
python scripts/build_windows.py
```

然后从已有构建生成版本化 Portable 目录：

```powershell
python scripts/create_release.py
```

输出目录格式为：

```text
release/
└─ ReimbursementManager-0.2.2-win64/
```

构建和发布产物不包含用户数据库、日志、备份或报销附件。

### 更新本机已安装的版本

如果已经在本机安装过，构建完成后可以直接覆盖安装目录，不必再去 GitHub 下载：

```powershell
python scripts/deploy_local.py            # 构建 → 复制 → 重建桌面快捷方式
python scripts/deploy_local.py --skip-build  # 跳过构建，部署现有 dist/
```

也可以双击 `scripts/deploy_local.cmd`。程序文件替换为整目录替换，用户数据位于 `%LOCALAPPDATA%\ReimbursementManager`，不受影响。

## 项目结构

```text
src/reimbursement_manager/
├─ app.py                 # 应用启动与服务装配
├─ updater.py             # 安装已下载的更新并重启（--apply-update 入口）
├─ config/                # 开发与发布运行路径
├─ database/              # SQLAlchemy 模型、仓储与 Alembic migration
├─ domain/                # 领域枚举
├─ services/              # 业务、文件、导出、备份与恢复服务
├─ ui/                    # PySide6 界面与 QSS 样式
└─ utils/

scripts/                  # 演示、构建和发布脚本
tests/                    # 业务、集成与 UI 测试
```

## 技术栈

Python 3.12+、PySide6、SQLite、SQLAlchemy 2.x、Alembic、pytest、PyInstaller。

## 版本控制与隐私

仓库只保存应用代码、测试、迁移、文档和构建配置。`.gitignore` 会排除本地数据库、附件归档、备份、日志、构建产物和虚拟环境，避免将真实报销材料提交到 Git。
