from collections.abc import Iterator
from datetime import date

import pytest
from sqlalchemy import func, select

from reimbursement_manager.database import DatabaseManager
from reimbursement_manager.database.models import (
    Attachment,
    Base,
    Item,
    MaterialRequirement,
    ReimbursementBatch,
)
from reimbursement_manager.database.repositories import (
    BatchRepository,
    ItemRepository,
    MaterialTypeRepository,
)
from reimbursement_manager.domain import ReimbursementStatus
from reimbursement_manager.services import (
    BatchNotFoundError,
    AttachmentService,
    ItemSequenceAlreadyExistsError,
    ItemService,
    StoragePathService,
    TemplateNotFoundError,
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


def create_batch(database: DatabaseManager, name: str = "实验耗材") -> int:
    with database.transaction() as session:
        batch = BatchRepository(session).create(ReimbursementBatch(name=name))
        return batch.id


def test_create_item_copies_template_materials_and_all_item_fields(
    database: DatabaseManager,
) -> None:
    template = TemplateService(database).ensure_default_template()
    batch_id = create_batch(database)

    item = ItemService(database).create_item(
        batch_id=batch_id,
        template_id=template.id,
        sequence_number=1,
        name="树莓派 Zero 2 W",
        purchase_date=date(2026, 8, 28),
        merchant="电子器材店",
        platform="淘宝",
        order_number="ORDER-001",
        quantity=2,
        unit_price_cents=12900,
        total_amount_cents=25800,
        notes="实验控制器",
    )

    assert item.id is not None
    assert item.batch_id == batch_id
    assert item.sequence_number == 1
    assert item.name == "树莓派 Zero 2 W"
    assert item.purchase_date == date(2026, 8, 28)
    assert item.merchant == "电子器材店"
    assert item.platform == "淘宝"
    assert item.order_number == "ORDER-001"
    assert item.quantity == 2
    assert item.unit_price_cents == 12900
    assert item.total_amount_cents == 25800
    assert item.status is ReimbursementStatus.COLLECTING
    assert item.notes == "实验控制器"
    assert [
        (value.material_type.code, value.required, value.sort_order)
        for value in item.requirements
    ] == [
        ("physical_photo", True, 1),
        ("payment_screenshot", True, 2),
        ("invoice", True, 3),
        ("order_screenshot", True, 4),
    ]


def test_existing_item_requirements_are_independent_of_template_changes(
    database: DatabaseManager,
) -> None:
    template_service = TemplateService(database)
    template = template_service.ensure_default_template()
    item_service = ItemService(database)
    item = item_service.create_item(
        batch_id=create_batch(database),
        template_id=template.id,
        sequence_number=1,
        name="树莓派 Zero 2 W",
        total_amount_cents=100,
    )

    template_service.set_material_required(
        template.id, "invoice", required=False
    )
    template_service.remove_material(template.id, "order_screenshot")

    stored = item_service.get_item(item.id)
    assert [
        (value.material_type.code, value.required)
        for value in stored.requirements
    ] == [
        ("physical_photo", True),
        ("payment_screenshot", True),
        ("invoice", True),
        ("order_screenshot", True),
    ]

    template_service.add_material(template.id, "order_detail", required=False)
    new_item = item_service.create_item(
        batch_id=item.batch_id,
        template_id=template.id,
        sequence_number=2,
        name="新采购物品",
    )
    assert [
        (value.material_type.code, value.required)
        for value in new_item.requirements
    ] == [
        ("physical_photo", True),
        ("payment_screenshot", True),
        ("invoice", False),
        ("order_detail", False),
    ]


def test_create_item_validates_parents_values_and_duplicate_sequence(
    database: DatabaseManager,
) -> None:
    template = TemplateService(database).ensure_default_template()
    batch_id = create_batch(database)
    service = ItemService(database)

    with pytest.raises(BatchNotFoundError):
        service.create_item(
            batch_id=999_999,
            template_id=template.id,
            sequence_number=1,
            name="不存在的批次",
        )
    with pytest.raises(TemplateNotFoundError):
        service.create_item(
            batch_id=batch_id,
            template_id=999_999,
            sequence_number=1,
            name="不存在的模板",
        )
    with pytest.raises(ValueError, match="name"):
        service.create_item(
            batch_id=batch_id,
            template_id=template.id,
            sequence_number=1,
            name="  ",
        )
    with pytest.raises(ValueError, match="sequence_number"):
        service.create_item(
            batch_id=batch_id,
            template_id=template.id,
            sequence_number=0,
            name="无效序号",
        )
    with pytest.raises(ValueError, match="quantity"):
        service.create_item(
            batch_id=batch_id,
            template_id=template.id,
            sequence_number=1,
            name="无效数量",
            quantity=0,
        )
    with pytest.raises(ValueError, match="total_amount_cents"):
        service.create_item(
            batch_id=batch_id,
            template_id=template.id,
            sequence_number=1,
            name="无效金额",
            total_amount_cents=-1,
        )

    service.create_item(
        batch_id=batch_id,
        template_id=template.id,
        sequence_number=1,
        name="第一个物品",
    )
    with pytest.raises(ItemSequenceAlreadyExistsError):
        service.create_item(
            batch_id=batch_id,
            template_id=template.id,
            sequence_number=1,
            name="重复序号",
        )


def test_requirement_copy_failure_rolls_back_item_and_requirements(
    database: DatabaseManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    template = TemplateService(database).ensure_default_template()
    batch_id = create_batch(database)
    original_create_requirement = ItemRepository.create_requirement
    call_count = 0

    def fail_on_second_requirement(
        repository: ItemRepository, requirement: MaterialRequirement
    ) -> MaterialRequirement:
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise RuntimeError("simulated requirement copy failure")
        return original_create_requirement(repository, requirement)

    monkeypatch.setattr(
        ItemRepository, "create_requirement", fail_on_second_requirement
    )

    with pytest.raises(RuntimeError, match="simulated requirement copy failure"):
        ItemService(database).create_item(
            batch_id=batch_id,
            template_id=template.id,
            sequence_number=1,
            name="必须整体回滚",
        )

    with database.transaction() as session:
        item_count = session.scalar(select(func.count()).select_from(Item))
        requirement_count = session.scalar(
            select(func.count()).select_from(MaterialRequirement)
        )
    assert item_count == 0
    assert requirement_count == 0


def test_search_items_matches_name_merchant_and_order_number(
    database: DatabaseManager,
) -> None:
    template = TemplateService(database).ensure_default_template()
    first_batch_id = create_batch(database, "实验耗材")
    second_batch_id = create_batch(database, "办公用品")
    service = ItemService(database)
    service.create_item(
        batch_id=first_batch_id,
        template_id=template.id,
        sequence_number=1,
        name="树莓派 Zero 2 W",
        merchant="电子器材店",
        order_number="ORDER-001",
    )
    service.create_item(
        batch_id=second_batch_id,
        template_id=template.id,
        sequence_number=1,
        name="HDMI 转接头",
        merchant="办公商城",
        order_number="ORDER-002",
    )

    assert [item.name for item in service.search_items("树莓派")] == [
        "树莓派 Zero 2 W"
    ]
    assert [item.name for item in service.search_items("电子器材")] == [
        "树莓派 Zero 2 W"
    ]
    assert [item.name for item in service.search_items("order-002")] == [
        "HDMI 转接头"
    ]
    assert [item.name for item in service.search_items()] == [
        "树莓派 Zero 2 W",
        "HDMI 转接头",
    ]


def test_delete_item_without_attachments_removes_item_and_requirements(
    database: DatabaseManager,
) -> None:
    template = TemplateService(database).ensure_default_template()
    item = ItemService(database).create_item(
        batch_id=create_batch(database),
        template_id=template.id,
        sequence_number=1,
        name="无附件物品",
    )

    ItemService(database).delete_item(item.id)

    with database.transaction() as session:
        assert session.get(Item, item.id) is None
        requirement_count = session.scalar(
            select(func.count()).select_from(MaterialRequirement)
        )
    assert requirement_count == 0


def test_delete_item_moves_attachments_to_trash(
    database: DatabaseManager, tmp_path
) -> None:
    template = TemplateService(database).ensure_default_template()
    batch_id = create_batch(database)
    storage = StoragePathService(tmp_path / "archive")
    attachments = AttachmentService(database, storage)
    items = ItemService(database, attachments)
    item = items.create_item(
        batch_id=batch_id,
        template_id=template.id,
        sequence_number=1,
        name="含附件物品",
    )
    with database.transaction() as session:
        invoice = MaterialTypeRepository(session).get_by_code("invoice")
        assert invoice is not None
        invoice_id = invoice.id
    source = tmp_path / "invoice.pdf"
    source.write_bytes(b"invoice")
    attachment = attachments.add_attachment(
        item_id=item.id, material_type_id=invoice_id, source_path=source
    )
    original_path = storage.resolve_relative_path(attachment.relative_path)
    trash_path = storage.get_attachment_trash_path(
        attachment_id=attachment.id, relative_path=attachment.relative_path
    )

    items.delete_item(item.id)

    assert not original_path.exists()
    assert trash_path.read_bytes() == b"invoice"
    with database.transaction() as session:
        assert session.get(Item, item.id) is None
        assert session.get(Attachment, attachment.id) is None


def test_delete_item_restores_files_when_item_database_delete_fails(
    database: DatabaseManager, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    template = TemplateService(database).ensure_default_template()
    storage = StoragePathService(tmp_path / "archive")
    attachments = AttachmentService(database, storage)
    items = ItemService(database, attachments)
    item = items.create_item(
        batch_id=create_batch(database),
        template_id=template.id,
        sequence_number=1,
        name="回滚物品",
    )
    with database.transaction() as session:
        invoice = MaterialTypeRepository(session).get_by_code("invoice")
        assert invoice is not None
        invoice_id = invoice.id
    source = tmp_path / "invoice.pdf"
    source.write_bytes(b"invoice")
    attachment = attachments.add_attachment(
        item_id=item.id, material_type_id=invoice_id, source_path=source
    )
    original_path = storage.resolve_relative_path(attachment.relative_path)
    trash_path = storage.get_attachment_trash_path(
        attachment_id=attachment.id, relative_path=attachment.relative_path
    )

    def fail_item_delete(repository: ItemRepository, entity: Item) -> None:
        del repository, entity
        raise RuntimeError("simulated item database delete failure")

    monkeypatch.setattr(ItemRepository, "delete", fail_item_delete)

    with pytest.raises(RuntimeError, match="simulated item database delete failure"):
        items.delete_item(item.id)

    assert original_path.read_bytes() == b"invoice"
    assert not trash_path.exists()
    with database.transaction() as session:
        assert session.get(Item, item.id) is not None
        assert session.get(Attachment, attachment.id) is not None
