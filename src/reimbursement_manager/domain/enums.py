from enum import StrEnum


class ReimbursementStatus(StrEnum):
    """Persisted workflow state, independent of material completeness."""

    COLLECTING = "collecting"
    SUBMITTED = "submitted"
    REIMBURSED = "reimbursed"
    ARCHIVED = "archived"


class AttachmentHealth(StrEnum):
    """Health of an attachment's file on local storage."""

    OK = "ok"
    MISSING = "missing"


class FileOperationMode(StrEnum):
    """Supported ways to import a source file into managed storage."""

    COPY = "copy"
    MOVE = "move"
