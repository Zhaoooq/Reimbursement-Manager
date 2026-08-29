from collections.abc import Iterator

import pytest
from sqlalchemy import func, select

from reimbursement_manager.database import (
    DatabaseManager,
    initialize_default_material_types,
)
from reimbursement_manager.database.models import Base, Template, TemplateMaterial
from reimbursement_manager.services import (
    MaterialTypeNotFoundError,
    TemplateMaterialAlreadyExistsError,
    TemplateMaterialNotFoundError,
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


@pytest.fixture
def service(database: DatabaseManager) -> TemplateService:
    with database.transaction() as session:
        initialize_default_material_types(session)
    return TemplateService(database)


def test_template_crud_returns_eagerly_readable_entities(
    service: TemplateService,
) -> None:
    created = service.create_template("科研设备", "设备材料")

    assert created.id is not None
    assert created.materials == []
    assert service.get_template(created.id).name == "科研设备"
    assert [value.id for value in service.list_templates()] == [created.id]

    updated = service.update_template(
        created.id,
        name="科研设备采购",
        description="更新说明",
    )
    assert updated.name == "科研设备采购"
    assert updated.description == "更新说明"

    service.delete_template(created.id)
    with pytest.raises(TemplateNotFoundError):
        service.get_template(created.id)


def test_material_operations_support_add_required_order_and_remove(
    service: TemplateService,
) -> None:
    template = service.create_template("自定义")

    invoice = service.add_material(
        template.id, "invoice", required=False
    )
    photo = service.add_material(
        template.id, "physical_photo", required=True
    )
    assert invoice.sort_order == 1
    assert photo.sort_order == 2

    updated_invoice = service.set_material_required(
        template.id, "invoice", required=True
    )
    assert updated_invoice.required is True

    stored = service.get_template(template.id)
    assert [value.material_type.code for value in stored.materials] == [
        "invoice",
        "physical_photo",
    ]
    assert all(value.required for value in stored.materials)

    service.remove_material(template.id, "physical_photo")
    stored = service.get_template(template.id)
    assert [value.material_type.code for value in stored.materials] == ["invoice"]


def test_material_operations_raise_clear_errors(service: TemplateService) -> None:
    template = service.create_template("错误测试")
    service.add_material(template.id, "invoice")

    with pytest.raises(TemplateMaterialAlreadyExistsError):
        service.add_material(template.id, "invoice")
    with pytest.raises(MaterialTypeNotFoundError):
        service.add_material(template.id, "unknown_code")
    with pytest.raises(TemplateMaterialNotFoundError):
        service.remove_material(template.id, "payment_screenshot")
    with pytest.raises(TemplateNotFoundError):
        service.add_material(999_999, "invoice")
    with pytest.raises(ValueError, match="sort_order"):
        service.add_material(template.id, "payment_screenshot", sort_order=-1)


def test_default_template_has_four_required_materials_and_is_idempotent(
    database: DatabaseManager,
) -> None:
    service = TemplateService(database)

    first = service.ensure_default_template()
    second = service.ensure_default_template()

    assert second.id == first.id
    assert first.name == "普通购物"
    assert [
        (value.material_type.code, value.required, value.sort_order)
        for value in first.materials
    ] == [
        ("physical_photo", True, 1),
        ("payment_screenshot", True, 2),
        ("invoice", True, 3),
        ("order_screenshot", True, 4),
    ]

    with database.transaction() as session:
        template_count = session.scalar(select(func.count()).select_from(Template))
        material_count = session.scalar(
            select(func.count()).select_from(TemplateMaterial)
        )
    assert template_count == 1
    assert material_count == 4


def test_default_initializer_preserves_user_template_changes(
    database: DatabaseManager,
) -> None:
    service = TemplateService(database)
    template = service.ensure_default_template()
    service.set_material_required(template.id, "invoice", required=False)
    service.remove_material(template.id, "order_screenshot")

    initialized_again = service.ensure_default_template()

    assert [
        (value.material_type.code, value.required)
        for value in initialized_again.materials
    ] == [
        ("physical_photo", True),
        ("payment_screenshot", True),
        ("invoice", False),
    ]
