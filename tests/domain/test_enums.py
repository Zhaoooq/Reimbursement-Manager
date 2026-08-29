import json
from enum import StrEnum

import pytest

from reimbursement_manager.domain import (
    AttachmentHealth,
    FileOperationMode,
    ReimbursementStatus,
)


@pytest.mark.parametrize(
    ("enum_type", "expected"),
    [
        (
            ReimbursementStatus,
            {
                "COLLECTING": "collecting",
                "SUBMITTED": "submitted",
                "REIMBURSED": "reimbursed",
                "ARCHIVED": "archived",
            },
        ),
        (AttachmentHealth, {"OK": "ok", "MISSING": "missing"}),
        (FileOperationMode, {"COPY": "copy", "MOVE": "move"}),
    ],
)
def test_enum_members_have_stable_string_values(
    enum_type: type[StrEnum], expected: dict[str, str]
) -> None:
    assert {member.name: member.value for member in enum_type} == expected
    assert all(isinstance(member, str) for member in enum_type)


@pytest.mark.parametrize(
    "member",
    [
        ReimbursementStatus.COLLECTING,
        AttachmentHealth.MISSING,
        FileOperationMode.COPY,
    ],
)
def test_enum_members_serialize_and_round_trip(member: StrEnum) -> None:
    serialized = json.dumps({"value": member})

    assert json.loads(serialized) == {"value": member.value}
    assert type(member)(member.value) is member


def test_reimbursement_status_excludes_material_completeness() -> None:
    member_names = ReimbursementStatus.__members__

    assert "COMPLETE" not in member_names
    assert "INCOMPLETE" not in member_names
    assert "READY" not in member_names
