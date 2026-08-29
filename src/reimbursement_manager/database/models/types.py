from enum import StrEnum
from typing import TypeVar

from sqlalchemy import Enum as SqlEnum


EnumMember = TypeVar("EnumMember", bound=StrEnum)


def persisted_enum(
    enum_class: type[EnumMember], *, name: str
) -> SqlEnum[EnumMember]:
    """Build a non-native enum that stores explicit string values."""
    return SqlEnum(
        enum_class,
        name=name,
        native_enum=False,
        create_constraint=False,
        validate_strings=True,
        values_callable=lambda members: [member.value for member in members],
    )
