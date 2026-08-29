# Item Creation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create an Item and copy a Template's materials into independent MaterialRequirements in one atomic transaction.

**Architecture:** `ItemService` owns validation and the transaction. `ItemRepository` persists the Item aggregate and provides eager reads; `TemplateRepository` supplies the source snapshot.

**Tech Stack:** Python 3.12, SQLAlchemy 2.0, SQLite, pytest

---

### Task 1: Specify Item creation behavior

**Files:**
- Create: `tests/services/test_item_service.py`

**Step 1: Write failing tests**

Cover Item field persistence, TemplateMaterial copying, detached eager reads, snapshot independence, clear validation errors, duplicate batch sequence handling, and rollback after a forced requirement-copy failure.

**Step 2: Verify failure**

Run: `.venv\\Scripts\\python.exe -m pytest tests/services/test_item_service.py -v`

Expected: FAIL because `ItemService` does not exist.

### Task 2: Extend ItemRepository for the Item aggregate

**Files:**
- Modify: `src/reimbursement_manager/database/repositories/item_repository.py`

**Step 1: Add scoped sequence lookup**

Query by `batch_id` and `sequence_number` to expose a recoverable business conflict before the database constraint fires.

**Step 2: Add MaterialRequirement persistence**

Create and flush child requirements without committing.

**Step 3: Add eager Item loading**

Load MaterialRequirements and their MaterialTypes, sorted by `sort_order` then ID.

### Task 3: Implement ItemService

**Files:**
- Create: `src/reimbursement_manager/services/item_service.py`
- Modify: `src/reimbursement_manager/services/__init__.py`

**Step 1: Add explicit business errors and validation**

Handle missing Batch/Template, duplicate sequence number, blank name, invalid quantities, and negative monetary values.

**Step 2: Implement atomic creation**

Create the Item and copy every TemplateMaterial into a new MaterialRequirement within one `DatabaseManager.transaction()` context.

**Step 3: Return an eager aggregate**

Reload the Item with requirements and MaterialTypes before the transaction closes.

### Task 4: Verify focused and full behavior

**Files:**
- No additional files.

**Step 1: Run focused tests**

Run: `.venv\\Scripts\\python.exe -m pytest tests/services/test_item_service.py -v`

Expected: all ItemService tests PASS.

**Step 2: Run all tests**

Run: `.venv\\Scripts\\python.exe -m pytest`

Expected: all project tests PASS.

**Step 3: Run an in-memory business-chain demonstration**

Create a Batch, instantiate one Item from the default Template, and print the copied material codes without modifying the development database.
