from pathlib import Path

import pytest

from reimbursement_manager.services import DesktopIntegrationService


def test_open_file_and_folder_delegate_to_windows_shell(tmp_path: Path) -> None:
    opened: list[str] = []
    document = tmp_path / "invoice.pdf"
    document.write_bytes(b"invoice")
    service = DesktopIntegrationService(startfile=opened.append)

    service.open_file(document)
    service.open_folder(tmp_path)

    assert opened == [str(document), str(tmp_path)]


def test_open_file_rejects_a_missing_file_without_calling_shell(tmp_path: Path) -> None:
    opened: list[str] = []
    service = DesktopIntegrationService(startfile=opened.append)

    with pytest.raises(FileNotFoundError):
        service.open_file(tmp_path / "missing.pdf")

    assert opened == []
