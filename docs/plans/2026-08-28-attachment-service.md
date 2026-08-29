# Attachment Service and Duplicate Detection Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Import attachments into managed storage with automatic naming, Item-scoped duplicate detection, database persistence, and filesystem compensation on failure.

**Architecture:** `AttachmentService` owns the database transaction and coordinates existing narrow services. File publication occurs before Attachment flush, while an outer compensation guard removes the file if verification, flush, or commit fails.

**Tech Stack:** Python 3.12, SQLAlchemy 2.0, SQLite, pathlib, pytest

---

### Task 1: Specify attachment workflow behavior

**Files:**
- Create: `tests/services/test_attachment_service.py`

**Step 1: Write failing tests**

Cover successful import and metadata, repeated material indexes, Item-scoped duplicates, cross-Item duplicate allowance, requirement validation, supported extensions, target verification, and database failure compensation.

**Step 2: Verify failure**

Run: `.venv\\Scripts\\python.exe -m pytest tests/services/test_attachment_service.py -v`

Expected: FAIL because `AttachmentService` does not exist.

### Task 2: Expose attachment filesystem metadata

**Files:**
- Modify: `src/reimbursement_manager/services/file_service.py`
- Modify: `tests/services/test_file_service.py`

**Step 1: Add file size and directory filename queries**

Keep direct filesystem inspection inside FileService. Missing directories return no filenames; non-directory paths raise a clear error.

**Step 2: Verify FileService regression**

Run: `.venv\\Scripts\\python.exe -m pytest tests/services/test_file_service.py -v`

Expected: all FileService tests PASS.

### Task 3: Load Item attachment context

**Files:**
- Modify: `src/reimbursement_manager/database/repositories/item_repository.py`

**Step 1: Eager-load the Batch**

Extend the existing requirement query so AttachmentService can build a path after the Session closes without a lazy-load dependency.

### Task 4: Implement AttachmentService and duplicate detection

**Files:**
- Create: `src/reimbursement_manager/services/attachment_service.py`
- Modify: `src/reimbursement_manager/services/__init__.py`

**Step 1: Define recoverable business exceptions and supported extensions**

Add missing-requirement, unsupported-type, duplicate, copy-verification, and compensation errors.

**Step 2: Validate and detect Item-scoped duplicates**

Load the Item aggregate, find its requirement, hash the source, and reject an existing `(item_id, sha256)` before filesystem mutation.

**Step 3: Name, copy, and verify the target**

Use attachment count plus actual directory names, generate the relative and absolute paths, copy atomically, and compare target SHA256.

**Step 4: Persist and compensate failures**

Flush the Attachment and commit through the service transaction. On any post-copy failure, delete the copied target and retain cleanup errors explicitly.

### Task 5: Verify focused and full behavior

**Files:**
- No additional files.

**Step 1: Run focused tests**

Run: `.venv\\Scripts\\python.exe -m pytest tests/services/test_attachment_service.py tests/services/test_file_service.py -v`

Expected: all attachment and file tests PASS.

**Step 2: Run all tests**

Run: `.venv\\Scripts\\python.exe -m pytest`

Expected: all project tests PASS.

**Step 3: Run an isolated full import demonstration**

Create an in-memory database and temporary archive, import a Chinese-named invoice, and print Attachment metadata without modifying `data/app.db`.
