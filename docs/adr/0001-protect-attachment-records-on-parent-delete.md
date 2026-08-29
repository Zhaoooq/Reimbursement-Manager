# ADR-0001: Protect Attachment Records on Parent Delete

## Status
Accepted

## Context
`Attachment` rows point to ordinary files on local disk. A database cascade can delete rows, but it cannot move the corresponding files into the application trash or recover them when a later operation fails. Silently cascading from `Item` or `MaterialType` would therefore allow unmanaged orphan files and violate the cross-filesystem consistency rules in `AGENTS.md`.

## Decision
Use database `RESTRICT` behavior for `Item -> Attachment`, `MaterialType -> Attachment`, `Batch -> Item`, and all `MaterialType` references. ORM relationships for those paths will not use delete cascade and will delegate deletion enforcement to SQLite.

Deleting an Item with attachments must fail. A future application service must first move each attachment file to `.trash`, delete its database record transactionally, and only then delete the Item. Database-only dependent rows without filesystem side effects—`MaterialRequirement` and `TemplateMaterial`—may use `ON DELETE CASCADE` plus ORM delete-orphan behavior.

## Consequences

### Positive
- Attachment metadata cannot silently disappear while files remain on disk.
- Deletion orchestration has one explicit service-layer location.
- Database constraints provide a final safety net against accidental repository deletes.

### Negative
- Deleting a populated Item or Batch requires multiple explicit steps.
- Service code must provide understandable errors when a restricted delete is attempted.

### Neutral
- SQLite foreign-key enforcement must remain enabled on every connection.

## Alternatives Considered

**Cascade every child row**
- Rejected because SQL cascade cannot coordinate `.trash` file operations.

**Allow nullable attachment parents**
- Rejected because orphan attachment records cannot answer which reimbursement Item owns the file.

**Soft-delete every model**
- Rejected as premature complexity for Phase 1.

## References
- `AGENTS.md`, sections 11 and 13
- `PHASE1_TASKS.md`, Task 3 and Task 17

