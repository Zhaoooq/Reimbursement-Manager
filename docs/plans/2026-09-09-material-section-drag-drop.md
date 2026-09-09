# Material Section Drag and Drop Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Allow one or more local attachment files to be dropped directly onto the intended material section in Item Detail.

**Architecture:** Add a small `QFrame` subclass that owns drag/drop event handling and emits local paths. Keep attachment validation and persistence in `AttachmentService`; `MainWindow` only coordinates multiple existing single-file imports, error presentation, and one final refresh.

**Tech Stack:** Python 3.12, PySide6, pytest, Qt offscreen platform.

---

### Task 1: Lock down drag/drop behavior

**Files:**
- Test: `tests/ui/test_main_window.py`

**Step 1:** Add tests that construct Qt drag/drop events with `QMimeData` and `QUrl`.

**Step 2:** Verify a material section accepts local-file drags, records its active visual state, and rejects remote URLs.

**Step 3:** Verify dropping two local files imports both under the target material type and refreshes Item Detail.

**Step 4:** Run the new tests and confirm they fail before implementation.

### Task 2: Implement the material drop target

**Files:**
- Modify: `src/reimbursement_manager/ui/windows/main_window.py`
- Modify: `src/reimbursement_manager/ui/styles/base.qss`

**Step 1:** Add a `MaterialDropSection` subclass with `dragEnterEvent`, `dragLeaveEvent`, and `dropEvent`.

**Step 2:** Replace the material section's plain `QFrame` with the drop target and connect dropped paths to `MainWindow`.

**Step 3:** Extract the existing single-file import into a shared coordinator that supports multiple paths, continues after recoverable per-file errors, and refreshes once after successful imports.

**Step 4:** Add a concise drop hint and a highlighted `dropActive` QSS state.

### Task 3: Verify focused regressions

**Files:**
- Test: `tests/ui/test_main_window.py`

**Step 1:** Run the new drag/drop tests with `QT_QPA_PLATFORM=offscreen`.

**Step 2:** Run the existing Item Detail attachment tests.

**Step 3:** Run `compileall` for the changed Python modules and `git diff --check`.

**Step 4:** Inspect the final diff and leave committing to the user unless explicitly requested.
