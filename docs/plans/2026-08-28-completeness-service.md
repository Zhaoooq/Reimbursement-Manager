# Completeness Service and File Health Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Calculate live material completeness from Item requirements and present attachment files, while recording missing-file health safely.

**Architecture:** `CompletenessService` owns one transaction for Item/Attachment reads and health updates. It returns immutable result data rather than persisting derived completeness fields.

**Tech Stack:** Python 3.12, SQLAlchemy 2.0, SQLite, pathlib, pytest

---

### Task 1: Specify live completeness behavior

**Files:**
- Create: `tests/services/test_completeness_service.py`

**Step 1: Write failing tests**

Cover 3/4 and missing names, 4/4 after the invoice upload, external deletion health changes, restored-file recovery, multiple attachments for one material, no required materials, and missing Items.

**Step 2: Verify failure**

Run: `.venv\\Scripts\\python.exe -m pytest tests/services/test_completeness_service.py -v`

Expected: FAIL because `CompletenessService` does not exist.

### Task 2: Implement immutable completeness result types

**Files:**
- Create: `src/reimbursement_manager/services/completeness_service.py`

**Step 1: Define `MissingMaterial` and `CompletenessResult`**

Include counts, percent, completion flag, and stable missing-material identifiers.

**Step 2: Define missing Item behavior**

Reuse the established `ItemNotFoundError` rather than returning a partial result.

### Task 3: Calculate completeness and update file health

**Files:**
- Modify: `src/reimbursement_manager/services/completeness_service.py`
- Modify: `src/reimbursement_manager/services/__init__.py`

**Step 1: Resolve all Item attachments**

Use the stored relative path with StoragePathService and FileService; invalid or missing paths are unavailable.

**Step 2: Persist changed health values**

Set `OK` or `MISSING` only when the observed value changes and flush through AttachmentRepository.

**Step 3: Derive requirement satisfaction**

Count only required requirements and accept at least one available attachment for each material type.

### Task 4: Verify focused and full behavior

**Files:**
- No additional files.

**Step 1: Run focused tests**

Run: `.venv\\Scripts\\python.exe -m pytest tests/services/test_completeness_service.py -v`

Expected: all CompletenessService tests PASS.

**Step 2: Run all tests**

Run: `.venv\\Scripts\\python.exe -m pytest`

Expected: all project tests PASS.

**Step 3: Run an isolated 3/4 to 4/4 demonstration**

Import three required files, calculate missing invoice, import it, and show the result without modifying `data/app.db`.
