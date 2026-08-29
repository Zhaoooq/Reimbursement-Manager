# Storage Path Service Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build safe archive, Batch, Item, and Attachment paths while keeping database paths relative and relocatable.

**Architecture:** `StoragePathService` owns path composition and containment checks, while `NamingService` remains the only component sanitizer. Relative paths use `PurePosixPath`; absolute native paths are resolved from the injected archive root.

**Tech Stack:** Python 3.12 standard library, pytest

---

### Task 1: Specify storage-path behavior

**Files:**
- Create: `tests/services/test_storage_path_service.py`

**Step 1: Write failing tests**

Cover the required Chinese directory structure, POSIX database paths, archive-root relocation, sanitization, empty fallbacks, directory-length limits, no implicit directory creation, invalid stored filenames, and traversal attempts.

**Step 2: Verify failure**

Run: `.venv\\Scripts\\python.exe -m pytest tests/services/test_storage_path_service.py -v`

Expected: FAIL because `StoragePathService` does not exist.

### Task 2: Extend centralized component truncation

**Files:**
- Modify: `src/reimbursement_manager/services/naming_service.py`
- Test: `tests/services/test_naming_service.py`

**Step 1: Add an optional component length**

Allow `sanitize_component()` to truncate by UTF-16 code units after cleaning and reserved-name handling.

**Step 2: Preserve existing behavior**

Run the NamingService tests and confirm all existing results remain unchanged.

### Task 3: Implement StoragePathService

**Files:**
- Create: `src/reimbursement_manager/services/storage_path_service.py`
- Modify: `src/reimbursement_manager/services/__init__.py`

**Step 1: Normalize the configured archive root**

Expose an absolute root without creating it.

**Step 2: Build Batch and Item directories**

Use the required date and sequence prefixes plus centrally sanitized names.

**Step 3: Build database and absolute attachment paths**

Return a POSIX relative path for persistence and resolve it to a native absolute path when needed.

**Step 4: Reject unsafe paths**

Validate stored filenames and reject drive, UNC, absolute, dot-segment, and parent-traversal inputs.

### Task 4: Verify focused and full behavior

**Files:**
- No additional files.

**Step 1: Run focused tests**

Run: `.venv\\Scripts\\python.exe -m pytest tests/services/test_storage_path_service.py tests/services/test_naming_service.py -v`

Expected: all path and naming tests PASS.

**Step 2: Run all tests**

Run: `.venv\\Scripts\\python.exe -m pytest`

Expected: all project tests PASS.

**Step 3: Print representative relative and absolute paths**

Use a temporary archive root and verify no directories are created by path calculation.
