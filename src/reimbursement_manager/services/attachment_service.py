from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from sqlalchemy.orm import Session

from reimbursement_manager.database import DatabaseManager
from reimbursement_manager.database.models import (
    Attachment,
    Item,
    MaterialRequirement,
)
from reimbursement_manager.database.repositories import (
    AttachmentRepository,
    ItemRepository,
)
from reimbursement_manager.domain import AttachmentHealth
from reimbursement_manager.services.file_service import FileService
from reimbursement_manager.services.hash_service import HashService
from reimbursement_manager.services.item_service import ItemNotFoundError
from reimbursement_manager.services.naming_service import NamingService
from reimbursement_manager.services.storage_path_service import StoragePathService


SUPPORTED_ATTACHMENT_EXTENSIONS = frozenset(
    {
        ".pdf",
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".bmp",
        ".tif",
        ".tiff",
        ".heic",
        ".heif",
    }
)


class AttachmentServiceError(Exception):
    """Base exception for recoverable attachment-import failures."""


class MaterialRequirementNotFoundError(AttachmentServiceError, LookupError):
    def __init__(self, item_id: int, material_type_id: int) -> None:
        super().__init__(
            f"Item {item_id} does not require material type {material_type_id}."
        )
        self.item_id = item_id
        self.material_type_id = material_type_id


class UnsupportedAttachmentTypeError(AttachmentServiceError, ValueError):
    def __init__(self, extension: str) -> None:
        display_extension = extension or "<none>"
        super().__init__(
            f"Unsupported attachment file extension: {display_extension}"
        )
        self.extension = extension


class DuplicateAttachmentError(AttachmentServiceError, ValueError):
    def __init__(
        self, item_id: int, sha256: str, existing_attachment_id: int
    ) -> None:
        super().__init__(
            f"Item {item_id} already contains attachment "
            f"{existing_attachment_id} with SHA256 {sha256}."
        )
        self.item_id = item_id
        self.sha256 = sha256
        self.existing_attachment_id = existing_attachment_id


class AttachmentCopyVerificationError(AttachmentServiceError, OSError):
    def __init__(self, destination: Path) -> None:
        super().__init__(f"Copied attachment verification failed: {destination}")
        self.destination = destination


class AttachmentRollbackError(AttachmentServiceError):
    def __init__(
        self,
        destination: Path,
        operation_error: Exception,
        cleanup_error: Exception,
    ) -> None:
        super().__init__(
            f"Attachment import failed and copied file could not be removed: "
            f"{destination}"
        )
        self.destination = destination
        self.operation_error = operation_error
        self.cleanup_error = cleanup_error


class AttachmentNotFoundError(AttachmentServiceError, LookupError):
    def __init__(self, attachment_id: int) -> None:
        super().__init__(f"Attachment {attachment_id} does not exist.")
        self.attachment_id = attachment_id


class AttachmentRemovalRollbackError(AttachmentServiceError):
    def __init__(
        self,
        original_path: Path,
        operation_error: Exception,
        restore_error: Exception,
    ) -> None:
        super().__init__(
            f"Attachment removal failed and the file could not be restored: "
            f"{original_path}"
        )
        self.original_path = original_path
        self.operation_error = operation_error
        self.restore_error = restore_error


@dataclass(frozen=True)
class AttachmentTrashMove:
    """One physical attachment move that can be reversed after a DB rollback."""

    original_path: Path
    trash_path: Path


class AttachmentService:
    """Coordinate one attachment import across storage and SQLite."""

    def __init__(
        self,
        database: DatabaseManager,
        storage_path_service: StoragePathService,
        *,
        file_service: FileService | None = None,
        hash_service: HashService | None = None,
        naming_service: NamingService | None = None,
    ) -> None:
        self._database = database
        self._storage_path_service = storage_path_service
        self._file_service = file_service or FileService()
        self._hash_service = hash_service or HashService()
        self._naming_service = naming_service or NamingService()

    def add_attachment(
        self,
        *,
        item_id: int,
        material_type_id: int,
        source_path: Path,
    ) -> Attachment:
        source = Path(source_path)
        copied_path: Path | None = None

        try:
            with self._database.transaction() as session:
                item_repository = ItemRepository(session)
                item = item_repository.get_by_id_with_requirements(item_id)
                if item is None:
                    raise ItemNotFoundError(item_id)
                requirement = self._require_material_requirement(
                    item.requirements, item_id, material_type_id
                )

                extension = source.suffix.lower()
                if extension not in SUPPORTED_ATTACHMENT_EXTENSIONS:
                    raise UnsupportedAttachmentTypeError(extension)

                source_hash = self._hash_service.calculate_sha256(source)
                attachment_repository = AttachmentRepository(session)
                duplicate = attachment_repository.find_by_hash(
                    item_id=item_id, sha256=source_hash
                )
                if duplicate is not None:
                    raise DuplicateAttachmentError(
                        item_id, source_hash, duplicate.id
                    )

                existing_for_material = attachment_repository.list_by_material(
                    item_id=item_id, material_type_id=material_type_id
                )
                item_directory = self._storage_path_service.get_item_directory(
                    batch_name=item.batch.name,
                    batch_date=item.batch.created_at.date(),
                    sequence_number=item.sequence_number,
                    item_name=item.name,
                )
                existing_names = self._file_service.list_file_names(
                    item_directory
                )
                stored_filename = self._naming_service.generate_filename(
                    sequence_number=item.sequence_number,
                    item_name=item.name,
                    material_name=requirement.material_type.name,
                    file_index=len(existing_for_material) + 1,
                    extension=extension,
                    existing_names=existing_names,
                )
                relative_path = (
                    self._storage_path_service.get_attachment_relative_path(
                        batch_name=item.batch.name,
                        batch_date=item.batch.created_at.date(),
                        sequence_number=item.sequence_number,
                        item_name=item.name,
                        stored_filename=stored_filename,
                    )
                )
                destination = self._storage_path_service.resolve_relative_path(
                    relative_path
                )

                self._file_service.ensure_directory(destination.parent)
                copied_path = self._file_service.copy_file(source, destination)
                if not self._file_service.file_exists(copied_path):
                    raise AttachmentCopyVerificationError(copied_path)
                copied_hash = self._hash_service.calculate_sha256(copied_path)
                if copied_hash != source_hash:
                    raise AttachmentCopyVerificationError(copied_path)

                attachment = attachment_repository.create(
                    Attachment(
                        item_id=item_id,
                        material_type_id=material_type_id,
                        original_filename=source.name,
                        stored_filename=stored_filename,
                        relative_path=relative_path.as_posix(),
                        file_extension=extension,
                        file_size=self._file_service.get_file_size(copied_path),
                        sha256=source_hash,
                        health=AttachmentHealth.OK,
                    )
                )
            return attachment
        except Exception as operation_error:
            if copied_path is not None and self._file_service.file_exists(
                copied_path
            ):
                try:
                    self._file_service.delete_file(copied_path)
                except Exception as cleanup_error:
                    raise AttachmentRollbackError(
                        copied_path, operation_error, cleanup_error
                    ) from operation_error
            raise

    def list_attachments(self, item_id: int) -> list[Attachment]:
        """Return an Item's attachments for read-only presentation."""
        with self._database.transaction() as session:
            if ItemRepository(session).get_by_id(item_id) is None:
                raise ItemNotFoundError(item_id)
            return AttachmentRepository(session).list_by_item(item_id)

    def get_attachment_path(self, attachment_id: int) -> Path:
        """Return an attachment's current archive path for desktop actions."""
        with self._database.transaction() as session:
            attachment = AttachmentRepository(session).get_by_id(attachment_id)
            if attachment is None:
                raise AttachmentNotFoundError(attachment_id)
            return self._storage_path_service.resolve_relative_path(
                attachment.relative_path
            )

    def remove_attachment(self, attachment_id: int) -> None:
        original_path: Path | None = None
        trash_path: Path | None = None
        moved_to_trash = False

        try:
            with self._database.transaction() as session:
                attachment_repository = AttachmentRepository(session)
                attachment = attachment_repository.get_by_id(attachment_id)
                if attachment is None:
                    raise AttachmentNotFoundError(attachment_id)

                try:
                    original_path = (
                        self._storage_path_service.resolve_relative_path(
                            attachment.relative_path
                        )
                    )
                except ValueError:
                    original_path = None

                if (
                    original_path is not None
                    and self._file_service.file_exists(original_path)
                ):
                    trash_path = (
                        self._storage_path_service.get_attachment_trash_path(
                            attachment_id=attachment.id,
                            relative_path=attachment.relative_path,
                        )
                    )
                    self._file_service.ensure_directory(trash_path.parent)
                    self._file_service.move_file(original_path, trash_path)
                    moved_to_trash = True

                attachment_repository.delete(attachment)
        except Exception as operation_error:
            if (
                moved_to_trash
                and original_path is not None
                and trash_path is not None
                and self._file_service.file_exists(trash_path)
            ):
                try:
                    self._file_service.ensure_directory(original_path.parent)
                    self._file_service.move_file(trash_path, original_path)
                except Exception as restore_error:
                    raise AttachmentRemovalRollbackError(
                        original_path, operation_error, restore_error
                    ) from operation_error
            raise

    def move_item_attachments_to_trash(
        self, session: Session, item_id: int
    ) -> list[AttachmentTrashMove]:
        """Move an Item's managed files to Trash without changing database rows.

        The caller owns the database transaction.  That lets Item deletion
        restore all file moves when a later attachment, requirement, or Item
        database operation fails.
        """
        moves: list[AttachmentTrashMove] = []
        try:
            attachments = AttachmentRepository(session).list_by_item(item_id)
            for attachment in attachments:
                try:
                    original_path = self._storage_path_service.resolve_relative_path(
                        attachment.relative_path
                    )
                except ValueError:
                    continue
                if not self._file_service.file_exists(original_path):
                    continue

                trash_path = self._storage_path_service.get_attachment_trash_path(
                    attachment_id=attachment.id,
                    relative_path=attachment.relative_path,
                )
                self._file_service.ensure_directory(trash_path.parent)
                self._file_service.move_file(original_path, trash_path)
                moves.append(AttachmentTrashMove(original_path, trash_path))
            return moves
        except Exception as operation_error:
            self.restore_item_attachment_moves(moves, operation_error)
            raise

    def restore_item_attachment_moves(
        self,
        moves: Iterable[AttachmentTrashMove],
        operation_error: Exception,
    ) -> None:
        """Restore Item attachment files after the caller's transaction failed."""
        for move in reversed(list(moves)):
            if not self._file_service.file_exists(move.trash_path):
                continue
            try:
                self._file_service.ensure_directory(move.original_path.parent)
                self._file_service.move_file(move.trash_path, move.original_path)
            except Exception as restore_error:
                raise AttachmentRemovalRollbackError(
                    move.original_path, operation_error, restore_error
                ) from operation_error

    def remove_item_directory_if_empty(self, item: Item) -> None:
        """Remove only an empty managed Item directory after a successful delete."""
        item_directory = self._storage_path_service.get_item_directory(
            batch_name=item.batch.name,
            batch_date=item.batch.created_at.date(),
            sequence_number=item.sequence_number,
            item_name=item.name,
        )
        try:
            item_directory.rmdir()
        except FileNotFoundError:
            return
        except OSError:
            # A non-empty directory may contain a user-managed file; retain it.
            return

    @staticmethod
    def _require_material_requirement(
        requirements: list[MaterialRequirement],
        item_id: int,
        material_type_id: int,
    ) -> MaterialRequirement:
        requirement = next(
            (
                value
                for value in requirements
                if value.material_type_id == material_type_id
            ),
            None,
        )
        if requirement is None:
            raise MaterialRequirementNotFoundError(item_id, material_type_id)
        return requirement
