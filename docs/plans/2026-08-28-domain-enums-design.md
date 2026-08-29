# Domain Enums Design

Task 1 introduces only the stable state codes needed by the Phase 1 domain. The implementation will use Python `StrEnum` with explicit lowercase values instead of `auto()`. Explicit values form a durable persistence contract: refactoring a Python member name later cannot silently change the value intended for storage. Because each member is also a string, repositories and future SQLAlchemy models can persist `.value` without maintaining a second conversion table, and JSON diagnostics can serialize members directly.

`ReimbursementStatus` represents reimbursement workflow only: `COLLECTING`, `SUBMITTED`, `REIMBURSED`, and `ARCHIVED`. It deliberately excludes material completeness and `READY`; completeness remains dynamically calculated from requirements and valid attachments as required by `AGENTS.md`. `AttachmentHealth` contains only `OK` and `MISSING`, which is enough for Phase 1 external-file detection. `FileOperationMode` contains `COPY` and `MOVE`; later attachment services will choose `COPY` as their default without embedding that policy inside the enum.

All enums live in `domain/enums.py`, and `domain/__init__.py` exposes the supported public names. Tests assert exact membership, stable string values, string/JSON serialization, and reconstruction from stored values. No SQLAlchemy column, database schema, display label, transition state machine, or UI behavior is added in this task. That keeps the change independent of Task 2 and Task 3 while giving those layers a stable vocabulary.

