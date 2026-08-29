# File Service Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Provide safe, bounded-memory file operations with atomic attachment publication and COPY as the default import mode.

**Architecture:** `FileService` performs only native filesystem mutations. Copies stream into a same-directory temporary file, sync and verify it, then rename it to a previously unused final path; higher services own database coordination.

**Tech Stack:** Python 3.12 standard library (`os`, `pathlib`, `shutil`, `tempfile`), pytest

---

### Task 1: Specify file-operation behavior

**Files:**
- Create: `tests/services/test_file_service.py`

**Step 1: Write failing tests**

Cover directory creation, regular-file existence, Chinese paths, default COPY, MOVE, DELETE, atomic publication, fsync, existing-target protection, missing paths, and temporary-file cleanup after a simulated failure.

**Step 2: Verify failure**

Run: `.venv\\Scripts\\python.exe -m pytest tests/services/test_file_service.py -v`

Expected: FAIL because `FileService` does not exist.

### Task 2: Implement basic filesystem operations

**Files:**
- Create: `src/reimbursement_manager/services/file_service.py`

**Step 1: Validate configuration**

Require a positive copy chunk size.

**Step 2: Implement directories and existence**

Create directories recursively and idempotently; report only regular files from `file_exists`.

**Step 3: Implement MOVE and DELETE**

Reject missing/non-file sources and existing destinations; rename for MOVE and unlink only regular files for DELETE.

### Task 3: Implement atomic COPY and mode dispatch

**Files:**
- Modify: `src/reimbursement_manager/services/file_service.py`
- Modify: `src/reimbursement_manager/services/__init__.py`

**Step 1: Copy to a same-directory temporary file**

Use bounded chunks, flush, fsync, close, and verify byte size.

**Step 2: Publish by rename and clean failures**

Never expose an incomplete destination and remove temporary files if any step fails.

**Step 3: Dispatch with COPY as the default**

Route `transfer_file` through COPY or MOVE using `FileOperationMode`.

### Task 4: Verify focused and full behavior

**Files:**
- No additional files.

**Step 1: Run focused tests**

Run: `.venv\\Scripts\\python.exe -m pytest tests/services/test_file_service.py -v`

Expected: all FileService tests PASS.

**Step 2: Run all tests**

Run: `.venv\\Scripts\\python.exe -m pytest`

Expected: all project tests PASS.

**Step 3: Run a temporary COPY demonstration**

Verify source and target both exist with identical content and no `.tmp` file remains.
