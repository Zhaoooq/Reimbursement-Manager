from collections.abc import Iterator

import pytest

from reimbursement_manager.database import DatabaseManager
from reimbursement_manager.database.models import (
    Attachment,
    Base,
    Item,
    MaterialType,
    ReimbursementBatch,
    Template,
)
from reimbursement_manager.database.repositories import (
    AttachmentRepository,
    BatchRepository,
    ItemRepository,
    MaterialTypeRepository,
    TemplateRepository,
)


@pytest.fixture
def database() -> Iterator[DatabaseManager]:
    manager = DatabaseManager.in_memory()
    Base.metadata.create_all(manager.engine)
    try:
        yield manager
    finally:
        manager.dispose()


def make_item(
    batch: ReimbursementBatch,
    sequence_number: int,
    name: str,
    *,
    merchant: str | None = None,
    order_number: str | None = None,
) -> Item:
    return Item(
        batch=batch,
        sequence_number=sequence_number,
        name=name,
        merchant=merchant,
        order_number=order_number,
        quantity=1,
        total_amount_cents=100,
    )


def make_attachment(
    item_id: int,
    material_type_id: int,
    suffix: str,
    sha256: str,
) -> Attachment:
    return Attachment(
        item_id=item_id,
        material_type_id=material_type_id,
        original_filename=f"{suffix}.pdf",
        stored_filename=f"{suffix}.pdf",
        relative_path=f"batch/{item_id}/{suffix}.pdf",
        file_extension=".pdf",
        file_size=100,
        sha256=sha256,
    )


def test_batch_repository_crud(database: DatabaseManager) -> None:
    with database.transaction() as session:
        repository = BatchRepository(session)
        created = repository.create(ReimbursementBatch(name="实验耗材"))
        batch_id = created.id

    with database.transaction() as session:
        repository = BatchRepository(session)
        stored = repository.get_by_id(batch_id)
        assert stored is not None
        assert repository.get_by_name("实验耗材") is stored
        stored.notes = "已核对"
        repository.update(stored)
        assert [batch.id for batch in repository.list()] == [batch_id]

    with database.transaction() as session:
        repository = BatchRepository(session)
        stored = repository.get_by_id(batch_id)
        assert stored is not None
        assert stored.notes == "已核对"
        repository.delete(stored)

    with database.transaction() as session:
        assert BatchRepository(session).get_by_id(batch_id) is None


def test_material_type_and_template_repository_crud(
    database: DatabaseManager,
) -> None:
    with database.transaction() as session:
        material_repository = MaterialTypeRepository(session)
        template_repository = TemplateRepository(session)
        material = material_repository.create(
            MaterialType(name="发票", code="invoice")
        )
        template = template_repository.create(Template(name="普通购物"))
        material_id = material.id
        template_id = template.id

    with database.transaction() as session:
        material_repository = MaterialTypeRepository(session)
        template_repository = TemplateRepository(session)
        material = material_repository.get_by_code("invoice")
        template = template_repository.get_by_name("普通购物")
        assert material is not None
        assert template is not None
        material.description = "PDF 或图片"
        template.description = "默认材料"
        material_repository.update(material)
        template_repository.update(template)
        assert [value.id for value in material_repository.list()] == [material_id]
        assert [value.id for value in template_repository.list()] == [template_id]

    with database.transaction() as session:
        material_repository = MaterialTypeRepository(session)
        template_repository = TemplateRepository(session)
        material = material_repository.get_by_id(material_id)
        template = template_repository.get_by_id(template_id)
        assert material is not None
        assert template is not None
        template_repository.delete(template)
        material_repository.delete(material)

    with database.transaction() as session:
        assert TemplateRepository(session).get_by_id(template_id) is None
        assert MaterialTypeRepository(session).get_by_id(material_id) is None


def test_item_repository_crud_and_searches_all_required_fields(
    database: DatabaseManager,
) -> None:
    with database.transaction() as session:
        batch_repository = BatchRepository(session)
        item_repository = ItemRepository(session)
        supplies = batch_repository.create(
            ReimbursementBatch(name="实验耗材报销")
        )
        travel = batch_repository.create(ReimbursementBatch(name="差旅报销"))
        first = item_repository.create(
            make_item(
                supplies,
                1,
                "树莓派 Zero 2 W",
                merchant="科技商店",
                order_number="ORDER-001",
            )
        )
        second = item_repository.create(
            make_item(
                supplies,
                2,
                "HDMI 转接头",
                merchant="电子城",
                order_number="ZX-999",
            )
        )
        third = item_repository.create(make_item(travel, 1, "出租车"))
        first_id, second_id, third_id = first.id, second.id, third.id
        supplies_id = supplies.id

    with database.transaction() as session:
        repository = ItemRepository(session)
        assert [item.id for item in repository.search("树莓派")] == [first_id]
        assert [item.id for item in repository.search("电子城")] == [second_id]
        assert [item.id for item in repository.search("ORDER-001")] == [first_id]
        assert [item.id for item in repository.search("差旅报销")] == [third_id]
        assert [item.id for item in repository.list_by_batch(supplies_id)] == [
            first_id,
            second_id,
        ]
        assert [item.id for item in repository.search("")] == [
            first_id,
            second_id,
            third_id,
        ]
        stored = repository.get_by_id(second_id)
        assert stored is not None
        stored.notes = "需补发票"
        repository.update(stored)

    with database.transaction() as session:
        repository = ItemRepository(session)
        stored = repository.get_by_id(third_id)
        assert stored is not None
        repository.delete(stored)

    with database.transaction() as session:
        repository = ItemRepository(session)
        assert repository.get_by_id(third_id) is None
        assert repository.get_by_id(second_id).notes == "需补发票"  # type: ignore[union-attr]


def test_item_search_treats_sql_wildcards_as_literal_text(
    database: DatabaseManager,
) -> None:
    with database.transaction() as session:
        batch = BatchRepository(session).create(ReimbursementBatch(name="报销"))
        repository = ItemRepository(session)
        percent = repository.create(make_item(batch, 1, "100% 纯铜"))
        repository.create(make_item(batch, 2, "1000 纯铜"))
        percent_id = percent.id

    with database.transaction() as session:
        results = ItemRepository(session).search("100%")
        assert [item.id for item in results] == [percent_id]


def test_attachment_repository_queries_are_item_scoped(
    database: DatabaseManager,
) -> None:
    with database.transaction() as session:
        batch = BatchRepository(session).create(ReimbursementBatch(name="报销"))
        item_repository = ItemRepository(session)
        material_repository = MaterialTypeRepository(session)
        first_item = item_repository.create(make_item(batch, 1, "A"))
        second_item = item_repository.create(make_item(batch, 2, "B"))
        invoice = material_repository.create(
            MaterialType(name="发票", code="invoice")
        )
        photo = material_repository.create(
            MaterialType(name="实物照片", code="physical_photo")
        )
        repository = AttachmentRepository(session)
        first_invoice = repository.create(
            make_attachment(first_item.id, invoice.id, "first-invoice", "a" * 64)
        )
        first_photo = repository.create(
            make_attachment(first_item.id, photo.id, "first-photo", "b" * 64)
        )
        second_invoice = repository.create(
            make_attachment(second_item.id, invoice.id, "second-invoice", "a" * 64)
        )
        ids = first_invoice.id, first_photo.id, second_invoice.id
        first_item_id, second_item_id = first_item.id, second_item.id
        invoice_id = invoice.id

    with database.transaction() as session:
        repository = AttachmentRepository(session)
        assert [value.id for value in repository.list_by_item(first_item_id)] == [
            ids[0],
            ids[1],
        ]
        assert [
            value.id
            for value in repository.list_by_material(
                item_id=first_item_id, material_type_id=invoice_id
            )
        ] == [ids[0]]
        assert repository.find_by_hash(
            item_id=first_item_id, sha256="a" * 64
        ).id == ids[0]  # type: ignore[union-attr]
        assert repository.find_by_hash(
            item_id=second_item_id, sha256="a" * 64
        ).id == ids[2]  # type: ignore[union-attr]
        stored = repository.get_by_id(ids[1])
        assert stored is not None
        repository.delete(stored)

    with database.transaction() as session:
        repository = AttachmentRepository(session)
        assert repository.get_by_id(ids[1]) is None
        assert repository.find_by_hash(
            item_id=first_item_id, sha256="f" * 64
        ) is None


def test_repository_flushes_but_never_commits(database: DatabaseManager) -> None:
    session = database.session_factory()
    try:
        repository = BatchRepository(session)
        created = repository.create(ReimbursementBatch(name="应回滚"))
        batch_id = created.id
        assert batch_id is not None
        session.rollback()
    finally:
        session.close()

    with database.transaction() as verification_session:
        assert BatchRepository(verification_session).get_by_id(batch_id) is None
