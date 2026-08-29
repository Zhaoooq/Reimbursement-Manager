# Project Bootstrap Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create the Phase 1 Task 0 Python project skeleton with a runnable package, local configuration, logging, and smoke tests.

**Architecture:** Use a `src` layout with a deliberately small application entry point. Configuration and logging stay in dedicated modules so later database and UI work can depend on them without introducing global mutable state.

**Tech Stack:** Python 3.12+, PySide6, SQLAlchemy 2.x, Alembic, pytest, setuptools

---

### Task 1: Define bootstrap acceptance tests

**Files:**
- Create: `tests/test_app.py`
- Create: `tests/config/test_settings.py`
- Create: `tests/utils/test_logging.py`

**Step 1: Write failing tests**

Cover the application return code, default project-relative paths, directory creation, and idempotent logging setup.

**Step 2: Run tests to verify they fail**

Run: `python -m pytest`

Expected: FAIL because the package modules do not exist yet.

### Task 2: Add package metadata and runtime skeleton

**Files:**
- Create: `pyproject.toml`
- Create: `src/reimbursement_manager/__init__.py`
- Create: `src/reimbursement_manager/__main__.py`
- Create: `src/reimbursement_manager/app.py`
- Create: `src/reimbursement_manager/config/__init__.py`
- Create: `src/reimbursement_manager/config/settings.py`
- Create: `src/reimbursement_manager/utils/__init__.py`
- Create: `src/reimbursement_manager/utils/logging.py`

**Step 1: Add minimal implementation**

Declare the Phase 1 dependencies, implement immutable application settings, configure rotating file and console logging, and expose a package entry point that exits successfully without creating premature UI.

**Step 2: Run focused tests**

Run: `python -m pytest`

Expected: PASS under Python 3.12+ with development dependencies installed.

### Task 3: Add project documentation and ignore rules

**Files:**
- Create: `.gitignore`
- Create: `README.md`

**Step 1: Document setup and commands**

Document Python 3.12 prerequisites, virtual-environment installation, `pytest`, and `python -m reimbursement_manager`.

**Step 2: Verify the package entry point**

Run: `python -m reimbursement_manager`

Expected: exit code 0 and a bootstrap log entry.
