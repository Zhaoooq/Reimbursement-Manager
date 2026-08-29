# Naming Service Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Generate readable, deterministic, collision-safe Windows attachment filenames in the project's required format.

**Architecture:** `NamingService` remains independent of Qt, SQLAlchemy, and filesystem I/O. It sanitizes individual components, enforces a UTF-16 filename budget, and resolves collisions from caller-provided existing names.

**Tech Stack:** Python 3.12 standard library, pytest

---

### Task 1: Specify filename behavior

**Files:**
- Create: `tests/services/test_naming_service.py`

**Step 1: Write failing tests**

Cover the canonical Chinese filename, Windows-invalid and control characters, surrounding whitespace, trailing periods, empty fallbacks, reserved device names, Unicode NFC, extension normalization, length limits, numeric validation, and case-insensitive collisions.

**Step 2: Verify failure**

Run: `.venv\\Scripts\\python.exe -m pytest tests/services/test_naming_service.py -v`

Expected: FAIL because `NamingService` does not exist.

### Task 2: Implement component sanitization

**Files:**
- Create: `src/reimbursement_manager/services/naming_service.py`

**Step 1: Define invalid and reserved names**

Use centralized constants for Windows-invalid characters, ASCII controls, and reserved device names.

**Step 2: Normalize one component**

Normalize to NFC, replace invalid runs, remove illegal trailing characters, apply a fallback, and protect reserved names.

### Task 3: Implement filename generation

**Files:**
- Modify: `src/reimbursement_manager/services/naming_service.py`
- Modify: `src/reimbursement_manager/services/__init__.py`

**Step 1: Validate numbers and extension**

Require positive sequence and file indexes and a non-empty cleaned extension.

**Step 2: Enforce the filename budget**

Measure UTF-16 code units and truncate only the Item and material components while preserving the naming structure and extension.

**Step 3: Resolve collisions**

Compare existing basenames with `casefold()` and increment the file index until the generated name is free.

### Task 4: Verify the service

**Files:**
- No additional files.

**Step 1: Run focused tests**

Run: `.venv\\Scripts\\python.exe -m pytest tests/services/test_naming_service.py -v`

Expected: all NamingService tests PASS.

**Step 2: Run all tests**

Run: `.venv\\Scripts\\python.exe -m pytest`

Expected: all project tests PASS.

**Step 3: Print representative output**

Generate the canonical Chinese filename plus one collision-resolved filename without touching the filesystem.
