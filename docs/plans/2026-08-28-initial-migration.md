# Initial Alembic Migration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add the first Alembic revision and prove it creates a schema identical to the seven SQLAlchemy models.

**Architecture:** Alembic configuration lives at the repository root, while migration code is colocated with the database package. The environment accepts test URL overrides and otherwise derives the local SQLite path from application settings.

**Tech Stack:** Python 3.12, Alembic 1.19, SQLAlchemy 2.0, SQLite, pytest

---

### Task 1: Specify migration acceptance behavior

**Files:**
- Create: `tests/database/migrations/test_migrations.py`

**Step 1: Write failing tests**

Use temporary SQLite files to test empty-database upgrade, repeated upgrade, current revision, metadata comparison, and downgrade.

**Step 2: Verify failure**

Run: `.venv\\Scripts\\python.exe -m pytest tests/database/migrations/test_migrations.py -v`

Expected: FAIL because the Alembic environment and revision do not exist.

### Task 2: Add Alembic environment and initial revision

**Files:**
- Create: `alembic.ini`
- Create: `src/reimbursement_manager/database/migrations/env.py`
- Create: `src/reimbursement_manager/database/migrations/script.py.mako`
- Create: `src/reimbursement_manager/database/migrations/versions/20260828_0001_initial_schema.py`

**Step 1: Configure migration metadata and URL handling**

Set `target_metadata = Base.metadata`, preserve programmatic URL overrides, and use `AppSettings.database_path` for the default CLI database.

**Step 2: Implement upgrade and downgrade**

Create and remove all tables, constraints, enum checks, and indexes in dependency-safe order.

**Step 3: Run focused tests**

Run: `.venv\\Scripts\\python.exe -m pytest tests/database/migrations/test_migrations.py -v`

Expected: PASS.

### Task 3: Document and verify the CLI workflow

**Files:**
- Modify: `README.md`

**Step 1: Document migration commands**

Add `alembic upgrade head` and `alembic current` instructions.

**Step 2: Run all tests and the real upgrade**

Run: `.venv\\Scripts\\python.exe -m pytest`

Run: `.venv\\Scripts\\alembic.exe upgrade head`

Expected: all tests PASS and `data/app.db` reaches revision `20260828_0001`.

