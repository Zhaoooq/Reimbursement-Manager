from pathlib import Path

import pytest

from reimbursement_manager.services import NamingService


def utf16_length(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def test_generates_required_chinese_filename() -> None:
    service = NamingService()

    filename = service.generate_filename(
        sequence_number=1,
        item_name="树莓派Zero2W",
        material_name="发票",
        file_index=1,
        extension=".PDF",
    )

    assert filename == "001_树莓派Zero2W_发票_01.pdf"


def test_sanitizes_invalid_characters_whitespace_and_trailing_periods() -> None:
    service = NamingService()

    assert service.sanitize_component('  A<B>:C.  ') == "A_B_C"
    assert service.sanitize_component("a\\b/c|d?e*f\x00") == "a_b_c_d_e_f"

    filename = service.generate_filename(
        sequence_number=7,
        item_name="  树莓派:Zero.  ",
        material_name="  发票/凭证. ",
        file_index=3,
        extension=" p:dF. ",
    )
    assert filename == "007_树莓派_Zero_发票_凭证_03.p_df"
    assert not any(character in filename for character in '<>:"/\\|?*')


def test_empty_names_use_readable_fallbacks() -> None:
    filename = NamingService().generate_filename(
        sequence_number=1,
        item_name=" . ",
        material_name="***",
        file_index=1,
        extension="pdf",
    )

    assert filename == "001_未命名物品_未命名材料_01.pdf"


@pytest.mark.parametrize(
    "reserved_name",
    [
        "CON",
        "prn",
        "AUX.txt",
        "nul",
        "COM1",
        "com9.log",
        "LPT1",
        "lpt9.txt",
    ],
)
def test_sanitizes_windows_reserved_names(reserved_name: str) -> None:
    sanitized = NamingService().sanitize_component(reserved_name)

    assert sanitized.startswith("_")
    assert sanitized.removeprefix("_") == reserved_name


def test_preserves_unicode_and_normalizes_to_nfc() -> None:
    decomposed = "Cafe\u0301 配件"

    sanitized = NamingService().sanitize_component(decomposed)

    assert sanitized == "Café 配件"


def test_enforces_utf16_length_while_preserving_structure() -> None:
    service = NamingService(max_filename_length=80)

    filename = service.generate_filename(
        sequence_number=1,
        item_name="😀超长物品名称" * 20,
        material_name="非常长的材料类型" * 20,
        file_index=1,
        extension="pdf",
    )

    assert utf16_length(filename) <= 80
    assert filename.startswith("001_")
    assert filename.endswith("_01.pdf")
    assert "😀" in filename
    assert "材料" in filename


def test_resolves_collisions_case_insensitively_by_incrementing_index() -> None:
    service = NamingService()
    first = service.generate_filename(
        sequence_number=1,
        item_name="Raspberry Pi",
        material_name="Invoice",
        file_index=1,
        extension="pdf",
    )

    second = service.generate_filename(
        sequence_number=1,
        item_name="Raspberry Pi",
        material_name="Invoice",
        file_index=1,
        extension="PDF",
        existing_names=[Path(first.upper())],
    )

    assert first == "001_Raspberry Pi_Invoice_01.pdf"
    assert second == "001_Raspberry Pi_Invoice_02.pdf"


@pytest.mark.parametrize(
    ("field", "kwargs"),
    [
        ("sequence_number", {"sequence_number": 0}),
        ("file_index", {"file_index": 0}),
        ("extension", {"extension": " . "}),
    ],
)
def test_rejects_invalid_numeric_fields_and_empty_extension(
    field: str, kwargs: dict[str, int | str]
) -> None:
    values: dict[str, int | str] = {
        "sequence_number": 1,
        "item_name": "物品",
        "material_name": "发票",
        "file_index": 1,
        "extension": "pdf",
    }
    values.update(kwargs)

    with pytest.raises(ValueError, match=field):
        NamingService().generate_filename(**values)  # type: ignore[arg-type]


def test_rejects_unusably_small_filename_limit() -> None:
    with pytest.raises(ValueError, match="max_filename_length"):
        NamingService(max_filename_length=20)
