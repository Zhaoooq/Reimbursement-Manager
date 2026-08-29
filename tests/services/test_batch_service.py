from __future__ import annotations

from collections.abc import Iterator

import pytest

from reimbursement_manager.database import DatabaseManager
from reimbursement_manager.database.models import Base
from reimbursement_manager.services import BatchNotEmptyError, ItemService, TemplateService
from reimbursement_manager.domain import ReimbursementStatus
from reimbursement_manager.services import BatchService


@pytest.fixture
def database() -> Iterator[DatabaseManager]:
    manager = DatabaseManager.in_memory()
    Base.metadata.create_all(manager.engine)
    try:
        yield manager
    finally:
        manager.dispose()


def test_create_batch_and_list_batches(database: DatabaseManager) -> None:
    service = BatchService(database)

    created = service.create_batch(name="八月实验耗材", project_name="传感器项目")

    assert created.name == "八月实验耗材"
    assert created.project_name == "传感器项目"
    assert created.status is ReimbursementStatus.COLLECTING
    assert [batch.id for batch in service.list_batches()] == [created.id]


def test_create_batch_rejects_blank_name(database: DatabaseManager) -> None:
    with pytest.raises(ValueError, match="name cannot be blank"):
        BatchService(database).create_batch(name="  ")


def test_list_batch_entries_includes_exact_item_totals(
    database: DatabaseManager,
) -> None:
    batch_service = BatchService(database)
    empty_batch = batch_service.create_batch(name="空批次")
    populated_batch = batch_service.create_batch(name="有物品批次")
    item_service = ItemService(database)
    template = TemplateService(database).ensure_default_template()
    item_service.create_item(
        batch_id=populated_batch.id,
        template_id=template.id,
        sequence_number=1,
        name="传感器",
        total_amount_cents=12345,
    )
    item_service.create_item(
        batch_id=populated_batch.id,
        template_id=template.id,
        sequence_number=2,
        name="连接线",
        total_amount_cents=55,
    )

    entries = batch_service.list_batch_entries()

    assert [(entry.id, entry.item_count, entry.total_amount_cents) for entry in entries] == [
        (empty_batch.id, 0, 0),
        (populated_batch.id, 2, 12400),
    ]
    assert [item.name for item in item_service.list_items_by_batch(populated_batch.id)] == [
        "传感器",
        "连接线",
    ]
    assert item_service.list_items_by_batch(empty_batch.id) == []


def test_delete_empty_batch_removes_it(database: DatabaseManager) -> None:
    service = BatchService(database)
    batch = service.create_batch(name="空批次")

    service.delete_batch(batch.id)

    assert service.list_batches() == []


def test_delete_non_empty_batch_is_rejected(database: DatabaseManager) -> None:
    service = BatchService(database)
    batch = service.create_batch(name="有物品批次")
    template = TemplateService(database).ensure_default_template()
    ItemService(database).create_item(
        batch_id=batch.id,
        template_id=template.id,
        sequence_number=1,
        name="物品",
    )

    with pytest.raises(BatchNotEmptyError):
        service.delete_batch(batch.id)

    assert [entry.id for entry in service.list_batch_entries()] == [batch.id]
