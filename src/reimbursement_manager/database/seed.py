from dataclasses import dataclass

from sqlalchemy.orm import Session

from reimbursement_manager.database.models import MaterialType
from reimbursement_manager.database.repositories import MaterialTypeRepository


@dataclass(frozen=True, slots=True)
class DefaultMaterialType:
    code: str
    name: str
    description: str


DEFAULT_MATERIAL_TYPES: tuple[DefaultMaterialType, ...] = (
    DefaultMaterialType(
        code="physical_photo",
        name="实物照片",
        description="报销物品的实物照片。",
    ),
    DefaultMaterialType(
        code="payment_screenshot",
        name="支付截图",
        description="支付成功或交易记录截图。",
    ),
    DefaultMaterialType(
        code="invoice",
        name="发票",
        description="与报销物品对应的发票文件。",
    ),
    DefaultMaterialType(
        code="order_screenshot",
        name="订单截图",
        description="订单列表或订单页面截图。",
    ),
    DefaultMaterialType(
        code="order_detail",
        name="订单详情",
        description="包含商品、数量和金额的订单明细。",
    ),
    DefaultMaterialType(
        code="other",
        name="其他",
        description="其他需要归档的补充报销材料。",
    ),
)


class DefaultMaterialTypeConflictError(ValueError):
    """Raised when a default display name belongs to a different code."""

    def __init__(
        self,
        default: DefaultMaterialType,
        existing: MaterialType,
    ) -> None:
        super().__init__(
            f"Default material type '{default.code}' cannot use name "
            f"'{default.name}'; that name belongs to code '{existing.code}'."
        )
        self.default = default
        self.existing = existing


def initialize_default_material_types(session: Session) -> list[MaterialType]:
    """Create missing defaults by stable code without committing the transaction."""
    repository = MaterialTypeRepository(session)
    existing_material_types = repository.list()
    by_code = {value.code: value for value in existing_material_types}
    by_name = {value.name: value for value in existing_material_types}
    initialized: list[MaterialType] = []

    for default in DEFAULT_MATERIAL_TYPES:
        material_type = by_code.get(default.code)
        if material_type is not None:
            initialized.append(material_type)
            continue

        conflicting_material_type = by_name.get(default.name)
        if conflicting_material_type is not None:
            raise DefaultMaterialTypeConflictError(
                default, conflicting_material_type
            )

        material_type = repository.create(
            MaterialType(
                code=default.code,
                name=default.name,
                description=default.description,
            )
        )
        by_code[material_type.code] = material_type
        by_name[material_type.name] = material_type
        initialized.append(material_type)

    return initialized
