from __future__ import annotations

import hashlib
from pathlib import Path


DEFAULT_HASH_CHUNK_SIZE = 1024 * 1024


class HashService:
    """Calculate SHA256 file digests with bounded-memory reads."""

    def __init__(self, *, chunk_size: int = DEFAULT_HASH_CHUNK_SIZE) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be greater than zero")
        self._chunk_size = chunk_size

    def calculate_sha256(self, path: Path) -> str:
        source_path = Path(path)
        if not source_path.exists():
            raise FileNotFoundError(f"File does not exist: {source_path}")
        if not source_path.is_file():
            raise IsADirectoryError(f"Expected a file: {source_path}")

        digest = hashlib.sha256()
        with source_path.open("rb") as source:
            while chunk := source.read(self._chunk_size):
                digest.update(chunk)
        return digest.hexdigest()
