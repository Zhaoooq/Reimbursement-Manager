# Phase 1 Integration Acceptance Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 为 Phase 1 增加可重复的端到端业务链路与故障补偿验收测试。

**Architecture:** 测试经由公开 Service API 驱动模板、物品、附件和完整性服务；数据库使用内存 SQLite，附件使用 pytest 临时目录。故障场景在文件服务或仓储边界注入，以验证跨文件系统和数据库操作的补偿行为。

**Tech Stack:** Python 3.12、pytest、SQLAlchemy 2.x、SQLite。

---

### Task 1: 添加完整业务链路集成测试

**Files:**
- Create: `tests/integration/test_phase1_workflow.py`

**Steps:**
1. 建立临时数据库与归档目录 fixture。
2. 以默认模板创建批次和树莓派物品，验证四项要求快照。
3. 分阶段上传附件，并断言缺失发票、完整、外部删除后再次缺失的结果及健康状态。
4. 运行该测试文件。

### Task 2: 添加故障与文件名边界验收测试

**Files:**
- Create: `tests/integration/test_phase1_failure_scenarios.py`

**Steps:**
1. 覆盖源文件不存在与模拟目标目录无写权限。
2. 覆盖中文路径、Windows 非法字符和同名冲突的统一命名结果。
3. 模拟数据库写入失败，验证已复制文件会被补偿删除。
4. 运行集成测试和完整测试套件。
