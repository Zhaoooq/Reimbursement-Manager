# Domain Enums Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Define the minimal Phase 1 domain enums with stable database-serializable string values and unit-test coverage.

**Architecture:** Keep workflow, attachment health, and file operation vocabulary in a dependency-free domain module. Use explicit `StrEnum` values as stable persistence codes while leaving display labels and database column definitions to later layers.

**Tech Stack:** Python 3.12 `enum.StrEnum`, pytest

---

### Task 1: Specify enum behavior with tests

**Files:**
- Create: `tests/domain/test_enums.py`

**Step 1: Write the failing tests**

Assert exact members and values for `ReimbursementStatus`, `AttachmentHealth`, and `FileOperationMode`; verify string/JSON serialization and value round-trips.

**Step 2: Run the focused test**

Run: `.venv\\Scripts\\python.exe -m pytest tests/domain/test_enums.py -v`

Expected: FAIL because `reimbursement_manager.domain` does not exist.

### Task 2: Implement the domain enums

**Files:**
- Create: `src/reimbursement_manager/domain/__init__.py`
- Create: `src/reimbursement_manager/domain/enums.py`

**Step 1: Implement explicit string enums**

Add only the members required by Task 1, with lowercase persistence values.

**Step 2: Run focused and full tests**

Run: `.venv\\Scripts\\python.exe -m pytest tests/domain/test_enums.py -v`

Expected: PASS.

Run: `.venv\\Scripts\\python.exe -m pytest`

Expected: all tests PASS.

