# Default Material Types Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add an idempotent initializer for the six stable Phase 1 material type codes without overwriting user-facing customizations.

**Architecture:** A database seed module owns immutable default definitions and uses `MaterialTypeRepository` within a caller-owned transaction. Existing codes are preserved; conflicting names raise a clear error and roll back through the outer transaction.

**Tech Stack:** Python 3.12 dataclasses, SQLAlchemy 2.0, pytest

---

### Task 1: Specify initialization behavior

**Files:**
- Create: `tests/database/test_seed.py`

**Step 1: Write failing tests**

Cover exact defaults, deterministic order, repeated execution, custom-name preservation, name conflicts, rollback, and no internal commit.

**Step 2: Verify failure**

Run: `.venv\\Scripts\\python.exe -m pytest tests/database/test_seed.py -v`

Expected: FAIL because `reimbursement_manager.database.seed` does not exist.

### Task 2: Implement the default catalog and initializer

**Files:**
- Create: `src/reimbursement_manager/database/seed.py`
- Modify: `src/reimbursement_manager/database/__init__.py`

**Step 1: Define immutable defaults and a conflict error**

Add six code/name/description definitions and an error that reports an occupied default name.

**Step 2: Implement insert-missing-by-code behavior**

Load existing rows once, preserve existing codes, create missing rows through the repository, and never commit.

**Step 3: Run focused tests**

Run: `.venv\\Scripts\\python.exe -m pytest tests/database/test_seed.py -v`

Expected: PASS.

### Task 3: Seed the migrated development database and regress

**Files:**
- No additional files.

**Step 1: Run all tests**

Run: `.venv\\Scripts\\python.exe -m pytest`

Expected: all tests PASS.

**Step 2: Initialize `data/app.db` twice**

Call the initializer twice in separate transactions and verify the database still contains exactly six rows.

