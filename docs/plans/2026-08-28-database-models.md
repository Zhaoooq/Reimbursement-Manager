# Database Models Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement and test the seven Phase 1 SQLAlchemy models with explicit relationships, constraints, indexes, timestamps, and safe deletion behavior.

**Architecture:** A shared declarative Base and timestamp mixin support small model modules. Database-only children cascade, while entities linked to attachment files use restrictive foreign keys according to ADR-0001.

**Tech Stack:** Python 3.12, SQLAlchemy 2.0 declarative mappings, SQLite, pytest

---

### Task 1: Specify model metadata and persistence behavior

**Files:**
- Create: `tests/database/models/test_models.py`

**Step 1: Write failing tests**

Test all table names, primary keys, timestamps, integer-cent columns, lowercase enum persistence, Unicode data, relationships, search indexes, uniqueness, and delete behavior.

**Step 2: Run tests to verify failure**

Run: `.venv\\Scripts\\python.exe -m pytest tests/database/models/test_models.py -v`

Expected: FAIL because the models package does not exist.

### Task 2: Add declarative infrastructure and model mappings

**Files:**
- Create: `src/reimbursement_manager/database/models/base.py`
- Create: `src/reimbursement_manager/database/models/types.py`
- Create: `src/reimbursement_manager/database/models/batch.py`
- Create: `src/reimbursement_manager/database/models/item.py`
- Create: `src/reimbursement_manager/database/models/material.py`
- Create: `src/reimbursement_manager/database/models/attachment.py`
- Create: `src/reimbursement_manager/database/models/template.py`
- Create: `src/reimbursement_manager/database/models/__init__.py`

**Step 1: Implement Base, timestamps, and persisted enum types**

Use `DeclarativeBase`, `Mapped`, `mapped_column`, timezone-aware column declarations, explicit lowercase enum values, and named constraints.

**Step 2: Implement the seven mappings**

Use integer cents, indexed search fields, unique parent/material pairs, item-scoped hash uniqueness, and the ADR-0001 cascade policy.

**Step 3: Run focused tests**

Run: `.venv\\Scripts\\python.exe -m pytest tests/database/models/test_models.py -v`

Expected: PASS.

### Task 3: Regression verification

**Files:**
- No additional files.

**Step 1: Run all tests**

Run: `.venv\\Scripts\\python.exe -m pytest`

Expected: all tests PASS.

**Step 2: Verify no production schema was created**

Confirm that model tests use temporary databases and that `data/app.db` is not created by imports.

