# Phase 2 UI Shell Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 构建可打开的 PySide6 基础窗口，显示导航和真实批次数据，并支持创建报销批次。

**Architecture:** 新增 `BatchService` 作为 UI 与 Repository 的业务边界。`MainWindow` 接收已初始化的数据库和归档路径，负责呈现与事件转发；应用入口负责迁移、默认数据和 Qt 生命周期。

**Tech Stack:** Python 3.12、PySide6、SQLAlchemy、Alembic、pytest。

---

### Task 1: 批次服务与测试

**Files:**
- Create: `src/reimbursement_manager/services/batch_service.py`
- Modify: `src/reimbursement_manager/services/__init__.py`
- Create: `tests/services/test_batch_service.py`

1. 写入批次创建、列出与空名称校验测试。
2. 运行测试确认服务尚不存在。
3. 实现事务边界明确的最小 `BatchService`。
4. 重跑测试。

### Task 2: 建立主窗口与 UI 测试

**Files:**
- Create: `src/reimbursement_manager/ui/windows/main_window.py`
- Create: `src/reimbursement_manager/ui/windows/__init__.py`
- Create: `src/reimbursement_manager/ui/__init__.py`
- Create: `tests/ui/test_main_window.py`

1. 编写离屏窗口构造与批次列表刷新测试。
2. 以深色导航、首页、批次页和占位页实现窗口。
3. 使用 `BatchService` 处理新建批次，不在 UI 写 SQL。
4. 运行 UI 测试。

### Task 3: 连接应用入口

**Files:**
- Create: `src/reimbursement_manager/database/migration.py`
- Modify: `scripts/demo_phase1.py`
- Modify: `src/reimbursement_manager/app.py`
- Modify: `tests/test_app.py`

1. 将 Alembic 升级封装为可复用函数。
2. 启动应用时迁移、初始化默认数据、显示窗口、关闭时释放资源。
3. 保留可测试的 `run_event_loop=False` 路径。
4. 运行完整测试并实际打开窗口验证。
