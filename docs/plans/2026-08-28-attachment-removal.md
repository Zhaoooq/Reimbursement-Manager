# Attachment Removal Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remove Attachment records while moving existing files to a recoverable application trash folder and restoring them if database deletion fails.

**Architecture:** `AttachmentService` coordinates the SQLite transaction and FileService move. StoragePathService builds a contained, attachment-ID-scoped trash path, and the service's outer guard compensates filesystem changes after transaction failure.

**Tech Stack:** Python 3.12, SQLAlchemy 2.0, SQLite, pathlib, pytest

---

### Task 1: Specify recoverable attachment deletion

**Files:**
- Modify: `tests/services/test_attachment_service.py`

**Step 1: Write failing tests**

Cover movement to `.trash`, record deletion, preservation of file content, missing-file row deletion, missing attachment errors, and database-delete failure restoration.

**Step 2: Verify failure**

Run: `.venv\\Scripts\\python.exe -m pytest tests/services/test_attachment_service.py -v`

Expected: FAIL because `remove_attachment` does not exist.

### Task 2: Build safe trash paths

**Files:**
- Modify: `src/reimbursement_manager/services/storage_path_service.py`
- Modify: `tests/services/test_storage_path_service.py`

**Step 1: Add an attachment-ID-scoped trash path**

Validate the existing relative path and return `archive_root/.trash/{attachment_id}/{relative-path}` without creating directories.

### Task 3: Implement transactional removal and compensation

**Files:**
- Modify: `src/reimbursement_manager/services/attachment_service.py`
- Modify: `src/reimbursement_manager/services/__init__.py`

**Step 1: Add removal exceptions**

Expose explicit missing-attachment and failed-restoration errors.

**Step 2: Move before deleting the record**

Move regular files to the trash path, then delete and flush the Attachment in one service transaction.

**Step 3: Restore after database failure**

Move the trashed file back to its original path if the transaction fails after publication.

### Task 4: Verify focused and full behavior

**Files:**
- No additional files.

**Step 1: Run focused tests**

Run: `.venv\\Scripts\\python.exe -m pytest tests/services/test_attachment_service.py tests/services/test_storage_path_service.py -v`

Expected: all relevant tests PASS.

**Step 2: Run all tests**

Run: `.venv\\Scripts\\python.exe -m pytest`

Expected: all project tests PASS.

**Step 3: Run an isolated remove demonstration**

Import a temporary attachment, remove it, and print that its database record is gone while its trash file remains.
