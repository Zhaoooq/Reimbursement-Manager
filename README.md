# 报销材料管理器

一个 Windows 优先、单用户、本地运行的报销材料管理工具。项目当前处于 Phase 1，优先建立核心数据层与文件管理基础，尚未开发完整 GUI。

## 环境要求

- Python 3.12+
- Windows 10/11（优先支持）

## 本地开发

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

## 运行测试

```powershell
python -m pytest
```

## 数据库迁移

首次开发或更新代码后，使用 Alembic 把本地数据库升级到最新版本：

```powershell
alembic upgrade head
alembic current
```

默认数据库文件为 `data/app.db`。正式 Schema 只通过 Alembic Migration 升级，不依赖 `Base.metadata.create_all()`。

## 运行应用入口

```powershell
python -m reimbursement_manager
```

当前入口只负责初始化运行目录和日志，不会提前创建 GUI。默认运行数据位于项目的 `data/` 目录：

```text
data/
├─ app.db
├─ archive/
└─ logs/
```

## 项目结构

```text
src/reimbursement_manager/
├─ app.py
├─ __main__.py
├─ config/
└─ utils/

tests/
```

## Phase 1 演示

以下命令会在独立目录中创建示例批次、物品和三份附件，并输出缺失材料；不会修改正式的 `data/app.db`：

```powershell
python scripts/demo_phase1.py
```

默认演示数据位于 `data/phase1-demo/`。可通过 `--workspace` 指定其他位置：

```powershell
python scripts/demo_phase1.py --workspace C:\temp\reimbursement-phase1-demo
```

业务实现顺序以 `PHASE1_TASKS.md` 为准。
