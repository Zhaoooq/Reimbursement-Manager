# ADR-0002: Services Own Database Transactions

## Status
Accepted

## Context
Phase 1 operations will span multiple repositories. Creating an Item from a Template must create the Item and all copied MaterialRequirements atomically. Attachment import will also coordinate database writes with filesystem operations. If each Repository commits independently, later failures cannot roll back the full business operation.

## Decision
Repositories receive an existing SQLAlchemy `Session`. Their mutation methods add, delete, and `flush()` entities so generated identifiers and constraint failures are immediately visible, but they never call `commit()` or `rollback()`.

Application services own transaction boundaries through `DatabaseManager.transaction()`. Multiple repositories can therefore participate in one unit of work. Repositories remain responsible only for persistence operations and queries.

## Consequences

### Positive
- Multi-repository business operations remain atomic.
- Constraint errors surface before service code begins dependent work.
- Transaction lifecycle stays centralized and testable.

### Negative
- Repository callers must provide an active Session.
- Incorrect callers can leave a transaction unfinished if they bypass `DatabaseManager`.

### Neutral
- Repository methods return ORM entities tied to the caller's current unit of work.

## Alternatives Considered

**Commit inside every Repository mutation**
- Rejected because Item/template and attachment workflows require atomic multi-step rollback.

**Give each Repository its own Session Factory**
- Rejected because repositories used by one service could not share a transaction reliably.

**Hide SQLAlchemy behind detached DTOs immediately**
- Rejected as unnecessary abstraction for the local Phase 1 application.

## References
- `AGENTS.md`, sections 4, 11, and 21
- `PHASE1_TASKS.md`, Task 5 and Task 8

