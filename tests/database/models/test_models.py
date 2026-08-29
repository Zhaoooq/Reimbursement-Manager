from collections.abc import Iterator

import pytest
from sqlalchemy import Integer, inspect, select, text
from sqlalchemy.exc import IntegrityError

from reimbursement_manager.database import DatabaseManager
from reimbursement_manager.database.models import (
    Attachment,
    Base,
    Item,
    MaterialRequirement,
    MaterialType,
    ReimbursementBatch,
    Template,
    TemplateMaterial,
)
from reimbursement_manager.domain import AttachmentHealth, ReimbursementStatus


@pytest.fixture
def database() -> Iterator[DatabaseManager]:
    manager = DatabaseManager.in_memory()
    Base.metadata.create_all(manager.engine)
    try:
        yield manager
    finally:
        manager.dispose()


def test_metadata_contains_all_phase_one_tables() -> None:
    assert set(Base.metadata.tables) == {
        "attachments",
        "items",
        "material_requirements",
        "material_types",
        "reimbursement_batches",
        "template_materials",
        "templates",
    }

    for table in Base.metadata.tables.values():
        assert tuple(table.primary_key.columns)
        assert "created_at" in table.c
        assert "updated_at" in table.c


def test_item_money_uses_integer_cents_and_search_fields_are_indexed() -> None:
    assert isinstance(Item.__table__.c.unit_price_cents.type, Integer)
    assert isinstance(Item.__table__.c.total_amount_cents.type, Integer)

    indexed_columns = {
        column.name
        for index in Item.__table__.indexes
        for column in index.columns
    }
    assert {"batch_id", "name", "merchant", "order_number"} <= indexed_columns


def test_models_persist_unicode_and_lowercase_enum_values(
    database: DatabaseManager,
) -> None:
    with database.transaction() as session:
        batch = ReimbursementBatch(name="实验耗材报销")
        material_type = MaterialType(name="发票", code="invoice")
        session.add_all([batch, material_type])
        session.flush()
        item = Item(
            batch_id=batch.id,
            sequence_number=1,
            name="树莓派 Zero 2 W",
            quantity=1,
            unit_price_cents=19900,
            total_amount_cents=19900,
        )
        session.add(item)

    with database.transaction() as session:
        stored_status = session.scalar(
            text("SELECT status FROM reimbursement_batches")
        )
        stored_item = session.scalar(select(Item))

        assert stored_status == "collecting"
        assert stored_item is not None
        assert stored_item.name == "树莓派 Zero 2 W"
        assert stored_item.status is ReimbursementStatus.COLLECTING
        assert stored_item.created_at is not None
        assert stored_item.updated_at is not None


def test_relationships_link_the_business_hierarchy(
    database: DatabaseManager,
) -> None:
    with database.transaction() as session:
        batch = ReimbursementBatch(name="2026-08 报销")
        material_type = MaterialType(name="发票", code="invoice")
        template = Template(name="普通购物")
        session.add_all([batch, material_type, template])
        session.flush()

        item = Item(
            batch=batch,
            sequence_number=1,
            name="树莓派 Zero 2 W",
            quantity=1,
            total_amount_cents=19900,
        )
        requirement = MaterialRequirement(
            item=item,
            material_type=material_type,
            required=True,
            sort_order=1,
        )
        attachment = Attachment(
            item=item,
            material_type=material_type,
            original_filename="发票.pdf",
            stored_filename="001_树莓派Zero2W_发票_01.pdf",
            relative_path="2026-08/001/001_树莓派Zero2W_发票_01.pdf",
            file_extension=".pdf",
            file_size=1024,
            sha256="a" * 64,
        )
        template_material = TemplateMaterial(
            template=template,
            material_type=material_type,
            required=True,
            sort_order=1,
        )
        session.add_all([requirement, attachment, template_material])

    with database.transaction() as session:
        stored_item = session.scalar(select(Item))
        stored_template = session.scalar(select(Template))

        assert stored_item is not None
        assert stored_item.batch.name == "2026-08 报销"
        assert stored_item.requirements[0].material_type.code == "invoice"
        assert stored_item.attachments[0].health is AttachmentHealth.OK
        assert stored_template is not None
        assert stored_template.materials[0].material_type.code == "invoice"


def test_item_delete_is_restricted_until_attachments_are_removed(
    database: DatabaseManager,
) -> None:
    with database.transaction() as session:
        batch = ReimbursementBatch(name="报销")
        material_type = MaterialType(name="发票", code="invoice")
        item = Item(
            batch=batch,
            sequence_number=1,
            name="树莓派",
            quantity=1,
            total_amount_cents=100,
        )
        requirement = MaterialRequirement(
            item=item, material_type=material_type, required=True, sort_order=1
        )
        attachment = Attachment(
            item=item,
            material_type=material_type,
            original_filename="invoice.pdf",
            stored_filename="001_invoice_01.pdf",
            relative_path="batch/item/001_invoice_01.pdf",
            file_extension=".pdf",
            file_size=1,
            sha256="b" * 64,
        )
        session.add_all([batch, material_type, requirement, attachment])
        session.flush()
        item_id = item.id
        attachment_id = attachment.id

    with pytest.raises(IntegrityError):
        with database.transaction() as session:
            stored_item = session.get(Item, item_id)
            assert stored_item is not None
            session.delete(stored_item)

    with database.transaction() as session:
        assert session.get(Item, item_id) is not None
        stored_attachment = session.get(Attachment, attachment_id)
        assert stored_attachment is not None
        session.delete(stored_attachment)

    with database.transaction() as session:
        stored_item = session.get(Item, item_id)
        assert stored_item is not None
        session.delete(stored_item)

    with database.transaction() as session:
        assert session.get(Item, item_id) is None
        requirement_count = session.scalar(
            select(MaterialRequirement).where(
                MaterialRequirement.item_id == item_id
            )
        )
        assert requirement_count is None


def test_duplicate_hash_is_rejected_only_within_the_same_item(
    database: DatabaseManager,
) -> None:
    with database.transaction() as session:
        batch = ReimbursementBatch(name="报销")
        material_type = MaterialType(name="发票", code="invoice")
        first_item = Item(
            batch=batch,
            sequence_number=1,
            name="A",
            quantity=1,
            total_amount_cents=100,
        )
        second_item = Item(
            batch=batch,
            sequence_number=2,
            name="B",
            quantity=1,
            total_amount_cents=100,
        )
        session.add_all([batch, material_type, first_item, second_item])
        session.flush()
        first_item_id = first_item.id
        second_item_id = second_item.id
        material_type_id = material_type.id

    def attachment(item_id: int, suffix: str) -> Attachment:
        return Attachment(
            item_id=item_id,
            material_type_id=material_type_id,
            original_filename=f"{suffix}.pdf",
            stored_filename=f"{suffix}.pdf",
            relative_path=f"batch/{item_id}/{suffix}.pdf",
            file_extension=".pdf",
            file_size=1,
            sha256="c" * 64,
        )

    with database.transaction() as session:
        session.add(attachment(first_item_id, "first"))

    with pytest.raises(IntegrityError):
        with database.transaction() as session:
            session.add(attachment(first_item_id, "duplicate"))

    with database.transaction() as session:
        session.add(attachment(second_item_id, "other-item"))

    with database.transaction() as session:
        attachment_count = session.scalar(
            select(text("COUNT(*)")).select_from(Attachment)
        )
        assert attachment_count == 2


def test_template_delete_cascades_only_database_owned_materials(
    database: DatabaseManager,
) -> None:
    with database.transaction() as session:
        material_type = MaterialType(name="发票", code="invoice")
        template = Template(name="普通购物")
        template.materials.append(
            TemplateMaterial(
                material_type=material_type,
                required=True,
                sort_order=1,
            )
        )
        session.add(template)
        session.flush()
        template_id = template.id

    with database.transaction() as session:
        stored_template = session.get(Template, template_id)
        assert stored_template is not None
        session.delete(stored_template)

    with database.transaction() as session:
        assert session.scalar(select(TemplateMaterial)) is None
        assert session.scalar(select(MaterialType)) is not None


def test_schema_has_expected_named_unique_constraints() -> None:
    inspector_names = {
        constraint.name
        for model in (
            Item,
            MaterialRequirement,
            Attachment,
            TemplateMaterial,
        )
        for constraint in model.__table__.constraints
        if constraint.name is not None
    }

    assert {
        "uq_items_batch_sequence",
        "uq_material_requirements_item_type",
        "uq_attachments_item_sha256",
        "uq_attachments_relative_path",
        "uq_template_materials_template_type",
    } <= inspector_names

    assert inspect(ReimbursementBatch).relationships["items"].passive_deletes == "all"
