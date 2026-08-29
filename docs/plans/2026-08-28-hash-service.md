# Hash Service Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Calculate deterministic SHA256 file hashes with bounded-memory streaming reads.

**Architecture:** `HashService` is a stateless filesystem reader with a configurable positive chunk size. It returns a digest or propagates explicit file errors and has no database or UI dependencies.

**Tech Stack:** Python 3.12 standard library (`hashlib`, `pathlib`), pytest

---

### Task 1: Specify hashing behavior

**Files:**
- Create: `tests/services/test_hash_service.py`

**Step 1: Write failing tests**

Cover identical and different files, an empty file, a Unicode path, fixed-size multi-chunk reads, missing files, directories, and invalid chunk sizes.

**Step 2: Verify failure**

Run: `.venv\\Scripts\\python.exe -m pytest tests/services/test_hash_service.py -v`

Expected: FAIL because `HashService` does not exist.

### Task 2: Implement streaming SHA256

**Files:**
- Create: `src/reimbursement_manager/services/hash_service.py`
- Modify: `src/reimbursement_manager/services/__init__.py`

**Step 1: Validate configuration and source path**

Require a positive chunk size, an existing path, and a regular file.

**Step 2: Read and hash fixed-size chunks**

Open in binary mode, repeatedly call `read(chunk_size)`, update SHA256, and return `hexdigest()`.

**Step 3: Export the service**

Expose `HashService` from the services package.

### Task 3: Verify focused and full behavior

**Files:**
- No additional files.

**Step 1: Run focused tests**

Run: `.venv\\Scripts\\python.exe -m pytest tests/services/test_hash_service.py -v`

Expected: all HashService tests PASS.

**Step 2: Run all tests**

Run: `.venv\\Scripts\\python.exe -m pytest`

Expected: all project tests PASS.

**Step 3: Hash a temporary representative file**

Print its byte size and digest, then confirm the application entry still starts.
