# Database Session Layer Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add an injectable SQLAlchemy 2.x SQLite engine, session factory, and safe transaction lifecycle with file and in-memory test support.

**Architecture:** An instance-based `DatabaseManager` owns an Engine and `sessionmaker`; no global Session is created. A context manager centralizes commit, rollback, and close behavior, while SQLite connection setup enables foreign-key enforcement.

**Tech Stack:** Python 3.12, SQLAlchemy 2.0, SQLite, pytest

---

### Task 1: Specify connection and transaction behavior

**Files:**
- Create: `tests/database/test_session.py`

**Step 1: Write failing infrastructure tests**

Test a Unicode file path, SQLite connectivity, foreign-key enforcement, fresh sessions, commit, rollback, and shared in-memory state.

**Step 2: Verify failure**

Run: `.venv\\Scripts\\python.exe -m pytest tests/database/test_session.py -v`

Expected: FAIL because `reimbursement_manager.database` does not exist.

### Task 2: Implement the database manager

**Files:**
- Create: `src/reimbursement_manager/database/__init__.py`
- Create: `src/reimbursement_manager/database/session.py`

**Step 1: Implement engine builders and lifecycle management**

Create file-backed and shared in-memory SQLite engines, attach the foreign-key pragma listener, expose the session factory, and implement commit/rollback/close transaction handling.

**Step 2: Run focused tests**

Run: `.venv\\Scripts\\python.exe -m pytest tests/database/test_session.py -v`

Expected: PASS.

### Task 3: Run regression verification

**Files:**
- No additional files.

**Step 1: Run all tests**

Run: `.venv\\Scripts\\python.exe -m pytest`

Expected: all tests PASS.

**Step 2: Verify the application entry point**

Run: `.venv\\Scripts\\python.exe -m reimbursement_manager`

Expected: exit code 0.

