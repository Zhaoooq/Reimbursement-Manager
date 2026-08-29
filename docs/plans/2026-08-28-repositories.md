# Repository Layer Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement the five Phase 1 repositories with session-scoped CRUD, required Item search, Attachment queries, and transaction-safe flush behavior.

**Architecture:** Repositories receive one caller-owned SQLAlchemy Session and never commit. A private generic base removes CRUD duplication while specialized subclasses contain entity-specific queries only.

**Tech Stack:** Python 3.12, SQLAlchemy 2.0, SQLite, pytest

---

### Task 1: Specify Repository behavior

**Files:**
- Create: `tests/database/repositories/test_repositories.py`

**Step 1: Write failing tests**

Cover CRUD for all five repositories, Item search across four fields, Attachment Item/material/hash queries, deterministic ordering, and caller-controlled rollback.

**Step 2: Verify failure**

Run: `.venv\\Scripts\\python.exe -m pytest tests/database/repositories/test_repositories.py -v`

Expected: FAIL because the repositories package does not exist.

### Task 2: Implement shared CRUD and specialized queries

**Files:**
- Create: `src/reimbursement_manager/database/repositories/base.py`
- Create: `src/reimbursement_manager/database/repositories/batch_repository.py`
- Create: `src/reimbursement_manager/database/repositories/item_repository.py`
- Create: `src/reimbursement_manager/database/repositories/template_repository.py`
- Create: `src/reimbursement_manager/database/repositories/attachment_repository.py`
- Create: `src/reimbursement_manager/database/repositories/material_type_repository.py`
- Create: `src/reimbursement_manager/database/repositories/__init__.py`

**Step 1: Implement the generic CRUD base**

Add/create/delete operations call `Session.flush()` and never commit. Reads use deterministic primary-key order.

**Step 2: Implement entity-specific queries**

Add Batch/Template name lookup, MaterialType code lookup, four-field Item search, and Item-scoped Attachment material/hash queries.

**Step 3: Run focused tests**

Run: `.venv\\Scripts\\python.exe -m pytest tests/database/repositories/test_repositories.py -v`

Expected: PASS.

### Task 3: Regression verification

**Files:**
- No additional files.

**Step 1: Run all tests**

Run: `.venv\\Scripts\\python.exe -m pytest`

Expected: all tests PASS.

