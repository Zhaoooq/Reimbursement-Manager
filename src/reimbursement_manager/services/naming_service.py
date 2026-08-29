from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
import re
import unicodedata


DEFAULT_MAX_FILENAME_LENGTH = 240
MAX_EXTENSION_LENGTH = 16

_INVALID_WINDOWS_CHARACTERS = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')
_WINDOWS_RESERVED_NAMES = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        "CONIN$",
        "CONOUT$",
        *(f"COM{index}" for index in range(1, 10)),
        *(f"LPT{index}" for index in range(1, 10)),
    }
)


class NamingService:
    """Generate deterministic attachment filenames that are safe on Windows."""

    def __init__(
        self, *, max_filename_length: int = DEFAULT_MAX_FILENAME_LENGTH
    ) -> None:
        if max_filename_length < 32:
            raise ValueError("max_filename_length must be at least 32")
        if max_filename_length > 255:
            raise ValueError("max_filename_length cannot exceed 255")
        self._max_filename_length = max_filename_length

    def sanitize_component(
        self,
        value: str,
        *,
        fallback: str = "未命名",
        max_length: int | None = None,
    ) -> str:
        """Clean one user-controlled filename component."""
        if max_length is not None and max_length <= 0:
            raise ValueError("max_length must be greater than zero")
        normalized = unicodedata.normalize("NFC", value)
        cleaned = _INVALID_WINDOWS_CHARACTERS.sub("_", normalized)
        cleaned = cleaned.strip().strip(" ._")
        if not cleaned:
            cleaned = fallback

        device_stem = cleaned.split(".", maxsplit=1)[0].upper()
        if device_stem in _WINDOWS_RESERVED_NAMES:
            cleaned = f"_{cleaned}"
        if max_length is not None:
            cleaned = self._truncate_utf16(cleaned, max_length)
            if not cleaned:
                raise ValueError("max_length is too small for this component")
        return cleaned

    def generate_filename(
        self,
        *,
        sequence_number: int,
        item_name: str,
        material_name: str,
        file_index: int,
        extension: str,
        existing_names: Iterable[str | Path] = (),
    ) -> str:
        """Generate the first available filename at or after ``file_index``."""
        self._validate_positive(sequence_number, "sequence_number")
        self._validate_positive(file_index, "file_index")
        safe_item_name = self.sanitize_component(
            item_name, fallback="未命名物品"
        )
        safe_material_name = self.sanitize_component(
            material_name, fallback="未命名材料"
        )
        safe_extension = self._sanitize_extension(extension)
        occupied_names = {
            Path(existing_name).name.casefold()
            for existing_name in existing_names
        }

        candidate_index = file_index
        while True:
            candidate = self._build_filename(
                sequence_number=sequence_number,
                item_name=safe_item_name,
                material_name=safe_material_name,
                file_index=candidate_index,
                extension=safe_extension,
            )
            if candidate.casefold() not in occupied_names:
                return candidate
            candidate_index += 1

    def _build_filename(
        self,
        *,
        sequence_number: int,
        item_name: str,
        material_name: str,
        file_index: int,
        extension: str,
    ) -> str:
        sequence = f"{sequence_number:03d}"
        index = f"{file_index:02d}"
        fixed_portion = f"{sequence}___{index}.{extension}"
        component_budget = self._max_filename_length - self._utf16_length(
            fixed_portion
        )
        if component_budget < 2:
            raise ValueError(
                "max_filename_length is too small for the numeric fields "
                "and extension"
            )

        item_budget, material_budget = self._allocate_component_budgets(
            item_name, material_name, component_budget
        )
        safe_item_name = self._truncate_utf16(item_name, item_budget)
        safe_material_name = self._truncate_utf16(
            material_name, material_budget
        )
        filename = (
            f"{sequence}_{safe_item_name}_{safe_material_name}_{index}."
            f"{extension}"
        )
        if self._utf16_length(filename) > self._max_filename_length:
            raise ValueError("generated filename exceeds max_filename_length")
        return filename

    @classmethod
    def _allocate_component_budgets(
        cls, item_name: str, material_name: str, total_budget: int
    ) -> tuple[int, int]:
        item_length = cls._utf16_length(item_name)
        material_length = cls._utf16_length(material_name)
        if item_length + material_length <= total_budget:
            return item_length, material_length

        item_budget = min(item_length, max(1, total_budget // 2))
        material_budget = min(
            material_length, max(1, total_budget - item_budget)
        )
        remaining = total_budget - item_budget - material_budget

        if remaining > 0:
            item_extra = min(item_length - item_budget, remaining)
            item_budget += item_extra
            remaining -= item_extra
        if remaining > 0:
            material_budget += min(
                material_length - material_budget, remaining
            )
        return item_budget, material_budget

    def _sanitize_extension(self, extension: str) -> str:
        normalized = unicodedata.normalize("NFC", extension).strip()
        normalized = normalized.lstrip(".")
        cleaned = _INVALID_WINDOWS_CHARACTERS.sub("_", normalized)
        cleaned = cleaned.strip(" ._").lower()
        if not cleaned:
            raise ValueError("extension cannot be blank")
        return self._truncate_utf16(cleaned, MAX_EXTENSION_LENGTH)

    @staticmethod
    def _validate_positive(value: int, field_name: str) -> None:
        if value <= 0:
            raise ValueError(f"{field_name} must be greater than zero")

    @staticmethod
    def _utf16_length(value: str) -> int:
        return len(value.encode("utf-16-le")) // 2

    @classmethod
    def _truncate_utf16(cls, value: str, max_length: int) -> str:
        used_length = 0
        result: list[str] = []
        for character in value:
            character_length = cls._utf16_length(character)
            if used_length + character_length > max_length:
                break
            result.append(character)
            used_length += character_length
        return "".join(result)
