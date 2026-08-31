from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from reimbursement_manager.database import DatabaseManager
from reimbursement_manager.database.models import Base, Item, ReimbursementBatch
from reimbursement_manager.database.repositories import BatchRepository
from reimbursement_manager.domain import ReimbursementStatus
from reimbursement_manager.services import (
    CompletenessService,
    DashboardService,
    ItemService,
    StoragePathService,
    TemplateService,
)


@pytest.fixture
def database() -> Iterator[DatabaseManager]:
    manager = DatabaseManager.in_memory()
    Base.metadata.create_all(manager.engine)
    try:
        yield manager
    finally:
        manager.dispose()


def test_get_data_counts_material_completeness_and_workflow_statuses(
    database: DatabaseManager, tmp_path: Path
) -> None:
    template_service = TemplateService(database)
    required_template = template_service.ensure_default_template()
    template = template_service.create_template("No requirements")
    with database.transaction() as session:
        batch = BatchRepository(session).create(ReimbursementBatch(name="August"))

    item_service = ItemService(database)
    incomplete = item_service.create_item(
        batch_id=batch.id,
        template_id=required_template.id,
        sequence_number=1,
        name="Missing invoice",
    )
    complete = item_service.create_item(
        batch_id=batch.id,
        template_id=template.id,
        sequence_number=2,
        name="Complete material",
    )
    submitted = item_service.create_item(
        batch_id=batch.id,
        template_id=template.id,
        sequence_number=3,
        name="Submitted item",
    )
    reimbursed = item_service.create_item(
        batch_id=batch.id,
        template_id=template.id,
        sequence_number=4,
        name="Reimbursed item",
    )

    with database.transaction() as session:
        submitted_item = session.get(Item, submitted.id)
        reimbursed_item = session.get(Item, reimbursed.id)
        assert submitted_item is not None
        assert reimbursed_item is not None
        submitted_item.status = ReimbursementStatus.SUBMITTED
        reimbursed_item.status = ReimbursementStatus.REIMBURSED

    dashboard = DashboardService(
        database,
        CompletenessService(database, StoragePathService(tmp_path / "archive")),
    )

    data = dashboard.get_data()

    assert data.incomplete_count == 1
    assert data.complete_count == 1
    assert data.submitted_count == 1
    assert data.reimbursed_count == 1
    assert len(data.incomplete_items) == 1
    assert data.incomplete_items[0].item_id == incomplete.id
    assert data.incomplete_items[0].name == "Missing invoice"
    assert data.incomplete_items[0].completed_count == 0
    assert data.incomplete_items[0].required_count == 4
    assert data.incomplete_items[0].missing_materials == (
        "实物照片",
        "支付截图",
        "发票",
        "订单截图",
    )
