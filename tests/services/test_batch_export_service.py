from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
import zipfile

import pytest
from PySide6.QtGui import QColor, QImage

from reimbursement_manager.database import DatabaseManager
from reimbursement_manager.database.models import Base
from reimbursement_manager.database.repositories import MaterialTypeRepository
from reimbursement_manager.services import (
    AttachmentService,
    BatchService,
    BatchSubmissionMaterialsIncompleteError,
    CompletenessService,
    EmptyBatchExportError,
    ExportService,
    ExportTargetExistsError,
    FileService,
    ItemService,
    PaymentScreenshotMergeService,
    StoragePathService,
    SubmissionReadinessService,
    TemplateService,
)


def zip_file_names(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as archive:
        return sorted(archive.namelist())


@pytest.fixture
def database() -> Iterator[DatabaseManager]:
    manager = DatabaseManager.in_memory()
    Base.metadata.create_all(manager.engine)
    try:
        yield manager
    finally:
        manager.dispose()


def write_image(path: Path, *, color: str) -> Path:
    image = QImage(3, 2, QImage.Format.Format_RGB32)
    image.fill(QColor(color))
    assert image.save(str(path), "PNG")
    return path


def material_type_ids(database: DatabaseManager) -> dict[str, int]:
    with database.transaction() as session:
        repository = MaterialTypeRepository(session)
        return {
            code: repository.get_by_code(code).id  # type: ignore[union-attr]
            for code in (
                "physical_photo",
                "invoice",
                "order_screenshot",
                "payment_screenshot",
            )
        }


def create_item(
    database: DatabaseManager,
    storage: StoragePathService,
    tmp_path: Path,
    *,
    batch_id: int,
    sequence_number: int,
    name: str,
    ready: bool,
) -> tuple[int, AttachmentService]:
    template = TemplateService(database).ensure_default_template()
    item = ItemService(database).create_item(
        batch_id=batch_id,
        template_id=template.id,
        sequence_number=sequence_number,
        name=name,
    )
    attachments = AttachmentService(database, storage)
    sources = {
        "physical_photo": write_image(
            tmp_path / f"{sequence_number}-photo.png", color="red"
        ),
        "invoice": tmp_path / f"{sequence_number}-invoice.pdf",
        "order_screenshot": write_image(
            tmp_path / f"{sequence_number}-order.png", color="green"
        ),
        "payment_screenshot": write_image(
            tmp_path / f"{sequence_number}-payment.png", color="blue"
        ),
    }
    sources["invoice"].write_bytes(b"invoice")
    for code, source in sources.items():
        attachments.add_attachment(
            item_id=item.id,
            material_type_id=material_type_ids(database)[code],
            source_path=source,
        )
    if ready:
        PaymentScreenshotMergeService(database, storage).generate(item.id)
    return item.id, attachments


def make_batch(
    database: DatabaseManager, tmp_path: Path, *, name: str = "2026年8月实验耗材"
) -> tuple[int, StoragePathService]:
    batch = BatchService(database).create_batch(name=name)
    return batch.id, StoragePathService(tmp_path / "archive")


def test_exports_ready_batch_with_only_final_submission_materials_and_keeps_state(
    database: DatabaseManager, tmp_path: Path
) -> None:
    batch_id, storage = make_batch(database, tmp_path)
    first_id, attachments = create_item(
        database, storage, tmp_path, batch_id=batch_id, sequence_number=1,
        name="树莓派 Zero 2 W", ready=True,
    )
    second_id, _ = create_item(
        database, storage, tmp_path, batch_id=batch_id, sequence_number=2,
        name="SD卡", ready=True,
    )
    completeness = CompletenessService(database, storage).calculate(first_id)
    readiness = SubmissionReadinessService(database, storage).calculate(first_id)
    before_attachments = [
        (attachment.id, attachment.relative_path, attachment.stored_filename)
        for attachment in attachments.list_attachments(first_id)
    ]

    result = ExportService(database, storage).export_batch(batch_id, tmp_path / "export")

    assert result.item_count == 2
    assert result.file_count == 6
    assert result.output_path.is_dir()
    assert sorted(path.name for path in result.output_path.iterdir()) == [
        "001_树莓派 Zero 2 W", "002_SD卡"
    ]
    names = [path.name for path in result.output_path.rglob("*") if path.is_file()]
    assert len(names) == 6
    assert not any("订单截图" in name for name in names)
    assert not any("合并" in name for name in names)
    assert CompletenessService(database, storage).calculate(first_id) == completeness
    assert SubmissionReadinessService(database, storage).calculate(first_id) == readiness
    assert [
        (attachment.id, attachment.relative_path, attachment.stored_filename)
        for attachment in attachments.list_attachments(first_id)
    ] == before_attachments
    assert SubmissionReadinessService(database, storage).calculate(second_id).is_ready


def test_rejects_batch_when_any_item_is_not_submission_ready(
    database: DatabaseManager, tmp_path: Path
) -> None:
    batch_id, storage = make_batch(database, tmp_path)
    create_item(database, storage, tmp_path, batch_id=batch_id, sequence_number=1, name="树莓派", ready=True)
    incomplete_id, _ = create_item(
        database, storage, tmp_path, batch_id=batch_id, sequence_number=2,
        name="SD卡", ready=False,
    )

    with pytest.raises(BatchSubmissionMaterialsIncompleteError) as error:
        ExportService(database, storage).export_batch(batch_id, tmp_path / "export")

    assert error.value.incomplete_items[0].item_id == incomplete_id
    assert error.value.incomplete_items[0].item_name == "SD卡"
    assert error.value.incomplete_items[0].missing_material_names == ("合并支付截图",)
    assert not (tmp_path / "export").exists()


def test_force_exports_only_existing_final_materials_and_writes_utf8_report(
    database: DatabaseManager, tmp_path: Path
) -> None:
    batch_id, storage = make_batch(database, tmp_path)
    create_item(
        database, storage, tmp_path, batch_id=batch_id, sequence_number=1,
        name="树莓派 Zero 2 W", ready=False,
    )

    result = ExportService(database, storage).export_batch(
        batch_id, tmp_path / "export", force=True
    )

    assert result.forced is True
    assert result.file_count == 2
    assert result.report_path == result.output_path / "导出结果.txt"
    assert result.report_path.read_text(encoding="utf-8") == (
        "批次：2026年8月实验耗材\n\n"
        "导出模式：强制导出\n\n"
        "以下物品提交材料不完整：\n\n"
        "001 树莓派 Zero 2 W\n缺少：\n- 合并支付截图\n"
    )
    names = [path.name for path in result.output_path.rglob("*") if path.is_file()]
    assert any("实物图" in name for name in names)
    assert any("发票" in name for name in names)
    assert not any("订单截图" in name for name in names)
    assert not any("支付截图" in name for name in names)


def test_force_exports_existing_final_materials_when_invoice_is_missing(
    database: DatabaseManager, tmp_path: Path
) -> None:
    batch_id, storage = make_batch(database, tmp_path)
    item_id, attachments = create_item(
        database, storage, tmp_path, batch_id=batch_id, sequence_number=1,
        name="HDMI转接头", ready=False,
    )
    invoice = next(
        attachment
        for attachment in attachments.list_attachments(item_id)
        if attachment.original_filename.endswith("invoice.pdf")
    )
    attachments.remove_attachment(invoice.id)

    result = ExportService(database, storage).export_batch(
        batch_id, tmp_path / "export", force=True
    )

    assert result.file_count == 1
    assert result.incomplete_items[0].missing_material_names == ("发票", "合并支付截图")
    names = [path.name for path in result.output_path.rglob("*") if path.is_file()]
    assert any("实物图" in name for name in names)
    assert not any("发票" in name for name in names)
    assert not any("订单截图" in name for name in names)
    assert not any("支付截图" in name for name in names)


def test_does_not_overwrite_an_existing_batch_export_directory(
    database: DatabaseManager, tmp_path: Path
) -> None:
    batch_id, storage = make_batch(database, tmp_path)
    create_item(database, storage, tmp_path, batch_id=batch_id, sequence_number=1, name="树莓派", ready=True)
    destination = tmp_path / "export"
    exporter = ExportService(database, storage)
    first = exporter.export_batch(batch_id, destination)

    with pytest.raises(ExportTargetExistsError):
        exporter.export_batch(batch_id, destination)

    assert first.output_path.is_dir()


class _RemoveSourceOnCopyFileService(FileService):
    def __init__(self, source_to_remove: Path) -> None:
        super().__init__()
        self._source_to_remove = source_to_remove
        self._removed = False

    def copy_file(self, source: Path, destination: Path) -> Path:
        if not self._removed and Path(source) == self._source_to_remove:
            self._source_to_remove.unlink()
            self._removed = True
        return super().copy_file(source, destination)


def test_cleans_temporary_batch_directory_when_a_source_disappears_during_export(
    database: DatabaseManager, tmp_path: Path
) -> None:
    batch_id, storage = make_batch(database, tmp_path)
    item_id, attachments = create_item(
        database, storage, tmp_path, batch_id=batch_id, sequence_number=1,
        name="树莓派", ready=True,
    )
    invoice = next(
        attachment for attachment in attachments.list_attachments(item_id)
        if attachment.original_filename.endswith("invoice.pdf")
    )
    source_to_remove = storage.resolve_relative_path(invoice.relative_path)
    destination = tmp_path / "export"

    with pytest.raises(FileNotFoundError):
        ExportService(
            database, storage,
            file_service=_RemoveSourceOnCopyFileService(source_to_remove),
        ).export_batch(batch_id, destination)

    assert not destination.joinpath("2026年8月实验耗材").exists()
    assert list(destination.glob(".tmp_*")) == []


def test_force_export_cleans_temporary_directory_when_copy_fails(
    database: DatabaseManager, tmp_path: Path
) -> None:
    batch_id, storage = make_batch(database, tmp_path)
    item_id, attachments = create_item(
        database, storage, tmp_path, batch_id=batch_id, sequence_number=1,
        name="树莓派", ready=False,
    )
    invoice = next(
        attachment for attachment in attachments.list_attachments(item_id)
        if attachment.original_filename.endswith("invoice.pdf")
    )
    source_to_remove = storage.resolve_relative_path(invoice.relative_path)
    destination = tmp_path / "export"

    with pytest.raises(FileNotFoundError):
        ExportService(
            database, storage,
            file_service=_RemoveSourceOnCopyFileService(source_to_remove),
        ).export_batch(batch_id, destination, force=True)

    assert not destination.joinpath("2026年8月实验耗材").exists()
    assert list(destination.glob(".tmp_*")) == []


def test_empty_batch_does_not_create_an_export_directory(
    database: DatabaseManager, tmp_path: Path
) -> None:
    batch_id, storage = make_batch(database, tmp_path)

    with pytest.raises(EmptyBatchExportError):
        ExportService(database, storage).export_batch(batch_id, tmp_path / "export")

    assert not (tmp_path / "export").exists()


def test_sanitizes_the_batch_directory_name(
    database: DatabaseManager, tmp_path: Path
) -> None:
    batch_id, storage = make_batch(database, tmp_path, name="2026/08:实验耗材")
    create_item(database, storage, tmp_path, batch_id=batch_id, sequence_number=1, name="树莓派", ready=True)

    result = ExportService(database, storage).export_batch(batch_id, tmp_path / "export")

    assert result.output_path.name == "2026_08_实验耗材"


def test_exports_ready_batch_zip_with_the_same_final_submission_files(
    database: DatabaseManager, tmp_path: Path
) -> None:
    batch_id, storage = make_batch(database, tmp_path, name="2026年8月实验耗材")
    item_id, attachments = create_item(
        database, storage, tmp_path, batch_id=batch_id, sequence_number=1,
        name="树莓派 Zero 2 W", ready=True,
    )
    before_completeness = CompletenessService(database, storage).calculate(item_id)
    before_readiness = SubmissionReadinessService(database, storage).calculate(item_id)
    before_attachments = [
        (attachment.id, attachment.relative_path, attachment.stored_filename)
        for attachment in attachments.list_attachments(item_id)
    ]
    exporter = ExportService(database, storage)
    directory_result = exporter.export_batch(batch_id, tmp_path / "directory")
    zip_result = exporter.export_batch_zip(batch_id, tmp_path / "zip")

    assert zip_result.export_format == "zip"
    assert zip_result.output_path.name == "2026年8月实验耗材.zip"
    assert zip_result.item_count == directory_result.item_count
    assert zip_result.file_count == directory_result.file_count
    expected_names = sorted(
        (Path(directory_result.output_path.name) / path.relative_to(directory_result.output_path)).as_posix()
        for path in directory_result.output_path.rglob("*")
        if path.is_file()
    )
    names = zip_file_names(zip_result.output_path)
    assert names == expected_names
    assert any("支付截图" in name for name in names)
    assert not any("订单截图" in name for name in names)
    assert not any("支付截图_合并" in name for name in names)
    assert CompletenessService(database, storage).calculate(item_id) == before_completeness
    assert SubmissionReadinessService(database, storage).calculate(item_id) == before_readiness
    assert [
        (attachment.id, attachment.relative_path, attachment.stored_filename)
        for attachment in attachments.list_attachments(item_id)
    ] == before_attachments


def test_force_exports_batch_zip_with_utf8_report(
    database: DatabaseManager, tmp_path: Path
) -> None:
    batch_id, storage = make_batch(database, tmp_path, name="中文批次")
    create_item(
        database, storage, tmp_path, batch_id=batch_id, sequence_number=1,
        name="中文物品", ready=False,
    )

    result = ExportService(database, storage).export_batch_zip(
        batch_id, tmp_path / "export", force=True
    )

    assert result.forced is True
    assert result.report_path is None
    with zipfile.ZipFile(result.output_path) as archive:
        names = archive.namelist()
        report_name = next(name for name in names if name.endswith("导出结果.txt"))
        assert "中文批次/" in report_name
        assert "以下物品提交材料不完整" in archive.read(report_name).decode("utf-8")
    assert not any("订单截图" in name for name in names)
    assert not any("支付截图_合并" in name for name in names)


def test_does_not_overwrite_an_existing_batch_zip(
    database: DatabaseManager, tmp_path: Path
) -> None:
    batch_id, storage = make_batch(database, tmp_path)
    create_item(database, storage, tmp_path, batch_id=batch_id, sequence_number=1, name="树莓派", ready=True)
    exporter = ExportService(database, storage)
    first = exporter.export_batch_zip(batch_id, tmp_path / "export")

    with pytest.raises(ExportTargetExistsError):
        exporter.export_batch_zip(batch_id, tmp_path / "export")

    assert first.output_path.is_file()


def test_zip_failure_cleans_temporary_zip_and_batch_directory(
    database: DatabaseManager, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    batch_id, storage = make_batch(database, tmp_path)
    create_item(database, storage, tmp_path, batch_id=batch_id, sequence_number=1, name="树莓派", ready=True)
    destination = tmp_path / "export"

    def fail_write(self, filename, arcname=None, compress_type=None, compresslevel=None):
        raise OSError("zip write failed")

    monkeypatch.setattr(zipfile.ZipFile, "write", fail_write)
    with pytest.raises(OSError, match="zip write failed"):
        ExportService(database, storage).export_batch_zip(batch_id, destination)

    assert list(destination.glob("*.zip")) == []
    assert list(destination.glob(".tmp_*")) == []
