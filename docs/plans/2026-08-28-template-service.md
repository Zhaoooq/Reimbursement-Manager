# Template Service Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement transactional Template CRUD, material management, and an idempotent four-material “普通购物” default Template.

**Architecture:** `TemplateService` owns transactions through `DatabaseManager`; repositories perform persistence and eager queries. MaterialTypes are resolved by stable code and service-specific exceptions describe recoverable failures.

**Tech Stack:** Python 3.12, SQLAlchemy 2.0, pytest

---

### Task 1: Specify Template Service behavior

**Files:**
- Create: `tests/services/test_template_service.py`

**Step 1: Write failing tests**

Cover CRUD, eager returned relationships, material add/remove/required operations, ordering, missing/duplicate errors, default content, idempotence, and preservation of edits.

**Step 2: Verify failure**

Run: `.venv\\Scripts\\python.exe -m pytest tests/services/test_template_service.py -v`

Expected: FAIL because `TemplateService` does not exist.

### Task 2: Extend Template persistence queries

**Files:**
- Modify: `src/reimbursement_manager/database/repositories/template_repository.py`

**Step 1: Add eager Template reads**

Load TemplateMaterials and MaterialTypes with `selectinload` for get, name lookup, and listing.

**Step 2: Add TemplateMaterial persistence methods**

Implement get/list/create/update/delete methods scoped to Template and MaterialType IDs; flush without committing.

### Task 3: Implement TemplateService

**Files:**
- Create: `src/reimbursement_manager/services/template_service.py`
- Create: `src/reimbursement_manager/services/__init__.py`

**Step 1: Implement service errors and validation**

Add explicit not-found and duplicate errors plus name and sort-order checks.

**Step 2: Implement transactional CRUD and material operations**

Each public operation uses one `DatabaseManager.transaction()` context.

**Step 3: Implement the default Template**

Initialize default MaterialTypes and create the four required TemplateMaterials atomically only when “普通购物” is absent.

**Step 4: Run focused tests**

Run: `.venv\\Scripts\\python.exe -m pytest tests/services/test_template_service.py -v`

Expected: PASS.

### Task 4: Initialize development data and regress

**Files:**
- No additional files.

**Step 1: Run all tests**

Run: `.venv\\Scripts\\python.exe -m pytest`

Expected: all tests PASS.

**Step 2: Ensure the real default Template twice**

Verify `data/app.db` contains one “普通购物” Template with four required materials.

