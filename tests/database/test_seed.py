from collections.abc import Iterator

import pytest
from sqlalchemy import func, select

from reimbursement_manager.database import DatabaseManager
from reimbursement_manager.database.models import Base, MaterialType
from reimbursement_manager.database.seed import (
    DEFAULT_MATERIAL_TYPES,
    DefaultMaterialTypeConflictError,
    initialize_default_material_types,
)


@pytest.fixture
def database() -> Iterator[DatabaseManager]:
    manager = DatabaseManager.in_memory()
    Base.metadata.create_all(manager.engine)
    try:
        yield manager
    finally:
        manager.dispose()


def test_initializer_creates_exact_default_catalog(
    database: DatabaseManager,
) -> None:
    with database.transaction() as session:
        created = initialize_default_material_types(session)
        created_ids = [material_type.id for material_type in created]

    with database.transaction() as session:
        stored = list(session.scalars(select(MaterialType).order_by(MaterialType.id)))

    assert [material_type.id for material_type in stored] == created_ids
    assert [(value.code, value.name) for value in stored] == [
        ("physical_photo", "实物照片"),
        ("payment_screenshot", "支付截图"),
        ("invoice", "发票"),
        ("order_screenshot", "订单截图"),
        ("order_detail", "订单详情"),
        ("other", "其他"),
    ]
    assert len(DEFAULT_MATERIAL_TYPES) == 6
    assert all(value.description for value in stored)


def test_initializer_is_idempotent_across_transactions(
    database: DatabaseManager,
) -> None:
    with database.transaction() as session:
        first = initialize_default_material_types(session)
        first_ids = [value.id for value in first]

    with database.transaction() as session:
        second = initialize_default_material_types(session)
        second_ids = [value.id for value in second]

    with database.transaction() as session:
        row_count = session.scalar(select(func.count()).select_from(MaterialType))

    assert second_ids == first_ids
    assert row_count == 6


def test_initializer_preserves_existing_code_customizations(
    database: DatabaseManager,
) -> None:
    with database.transaction() as session:
        custom = MaterialType(
            name="我的发票",
            code="invoice",
            description="用户自定义说明",
        )
        session.add(custom)

    with database.transaction() as session:
        initialized = initialize_default_material_types(session)
        invoice = next(value for value in initialized if value.code == "invoice")
        assert invoice.name == "我的发票"
        assert invoice.description == "用户自定义说明"

    with database.transaction() as session:
        row_count = session.scalar(select(func.count()).select_from(MaterialType))
        assert row_count == 6


def test_name_conflict_raises_and_rolls_back_partial_defaults(
    database: DatabaseManager,
) -> None:
    with database.transaction() as session:
        session.add(MaterialType(name="发票", code="custom_invoice"))

    with pytest.raises(
        DefaultMaterialTypeConflictError,
        match="invoice.*custom_invoice",
    ):
        with database.transaction() as session:
            initialize_default_material_types(session)

    with database.transaction() as session:
        stored = list(session.scalars(select(MaterialType)))

    assert [(value.code, value.name) for value in stored] == [
        ("custom_invoice", "发票")
    ]


def test_initializer_flushes_but_does_not_commit(
    database: DatabaseManager,
) -> None:
    session = database.session_factory()
    try:
        initialized = initialize_default_material_types(session)
        assert all(value.id is not None for value in initialized)
        session.rollback()
    finally:
        session.close()

    with database.transaction() as session:
        row_count = session.scalar(select(func.count()).select_from(MaterialType))

    assert row_count == 0
