from __future__ import annotations

import os
from pathlib import Path
import shutil
from tempfile import NamedTemporaryFile

from reimbursement_manager.domain import FileOperationMode


DEFAULT_COPY_CHUNK_SIZE = 1024 * 1024


class FileCopyVerificationError(OSError):
    """Raised when a completed temporary copy has an unexpected size."""


class FileService:
    """Perform low-level local file operations without database concerns."""

    def __init__(
        self, *, copy_chunk_size: int = DEFAULT_COPY_CHUNK_SIZE
    ) -> None:
        if copy_chunk_size <= 0:
            raise ValueError("copy_chunk_size must be greater than zero")
        self._copy_chunk_size = copy_chunk_size

    def ensure_directory(self, path: Path) -> Path:
        directory = Path(path)
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def file_exists(self, path: Path) -> bool:
        return Path(path).is_file()

    def get_file_size(self, path: Path) -> int:
        return self._require_source_file(path).stat().st_size

    def list_file_names(self, directory: Path) -> list[str]:
        directory_path = Path(directory)
        if not directory_path.exists():
            return []
        if not directory_path.is_dir():
            raise NotADirectoryError(
                f"Expected a directory: {directory_path}"
            )
        return sorted(
            (
                child.name
                for child in directory_path.iterdir()
                if child.is_file()
            ),
            key=str.casefold,
        )

    def copy_file(self, source: Path, destination: Path) -> Path:
        source_path = self._require_source_file(source)
        destination_path = self._require_available_destination(destination)
        expected_size = source_path.stat().st_size
        temporary_path: Path | None = None

        try:
            with source_path.open("rb") as source_file:
                with NamedTemporaryFile(
                    mode="wb",
                    dir=destination_path.parent,
                    prefix=f".{destination_path.name}.",
                    suffix=".tmp",
                    delete=False,
                ) as temporary_file:
                    temporary_path = Path(temporary_file.name)
                    shutil.copyfileobj(
                        source_file,
                        temporary_file,
                        length=self._copy_chunk_size,
                    )
                    temporary_file.flush()
                    os.fsync(temporary_file.fileno())

            actual_size = temporary_path.stat().st_size
            if actual_size != expected_size:
                raise FileCopyVerificationError(
                    f"Copied size mismatch for {source_path}: expected "
                    f"{expected_size}, got {actual_size}"
                )

            if destination_path.exists():
                raise FileExistsError(
                    f"Destination already exists: {destination_path}"
                )
            os.rename(temporary_path, destination_path)
            temporary_path = None
            return destination_path
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()

    def move_file(self, source: Path, destination: Path) -> Path:
        source_path = self._require_source_file(source)
        destination_path = self._require_available_destination(destination)
        os.rename(source_path, destination_path)
        return destination_path

    def delete_file(self, path: Path) -> None:
        source_path = self._require_source_file(path)
        source_path.unlink()

    def transfer_file(
        self,
        source: Path,
        destination: Path,
        *,
        mode: FileOperationMode = FileOperationMode.COPY,
    ) -> Path:
        if mode is FileOperationMode.COPY:
            return self.copy_file(source, destination)
        if mode is FileOperationMode.MOVE:
            return self.move_file(source, destination)
        raise ValueError(f"Unsupported file operation mode: {mode}")

    @staticmethod
    def _require_source_file(path: Path) -> Path:
        source_path = Path(path)
        if not source_path.exists():
            raise FileNotFoundError(f"File does not exist: {source_path}")
        if not source_path.is_file():
            raise IsADirectoryError(f"Expected a file: {source_path}")
        return source_path

    @staticmethod
    def _require_available_destination(path: Path) -> Path:
        destination_path = Path(path)
        if destination_path.exists():
            raise FileExistsError(
                f"Destination already exists: {destination_path}"
            )
        parent = destination_path.parent
        if not parent.exists():
            raise FileNotFoundError(
                f"Destination directory does not exist: {parent}"
            )
        if not parent.is_dir():
            raise NotADirectoryError(
                f"Destination parent is not a directory: {parent}"
            )
        return destination_path
