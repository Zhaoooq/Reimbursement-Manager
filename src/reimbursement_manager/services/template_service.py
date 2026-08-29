from __future__ import annotations

from sqlalchemy.orm import Session

from reimbursement_manager.database import (
    DatabaseManager,
    initialize_default_material_types,
)
from reimbursement_manager.database.models import (
    MaterialType,
    Template,
    TemplateMaterial,
)
from reimbursement_manager.database.repositories import (
    MaterialTypeRepository,
    TemplateRepository,
)


DEFAULT_TEMPLATE_NAME = "普通购物"
DEFAULT_TEMPLATE_DESCRIPTION = "普通购物报销所需的默认材料。"
DEFAULT_TEMPLATE_MATERIAL_CODES: tuple[str, ...] = (
    "physical_photo",
    "payment_screenshot",
    "invoice",
    "order_screenshot",
)


class TemplateServiceError(Exception):
    """Base exception for recoverable template-service failures."""


class TemplateNotFoundError(TemplateServiceError, LookupError):
    def __init__(self, template_id: int) -> None:
        super().__init__(f"Template {template_id} does not exist.")
        self.template_id = template_id


class MaterialTypeNotFoundError(TemplateServiceError, LookupError):
    def __init__(self, material_type_code: str) -> None:
        super().__init__(
            f"Material type with code '{material_type_code}' does not exist."
        )
        self.material_type_code = material_type_code


class TemplateMaterialNotFoundError(TemplateServiceError, LookupError):
    def __init__(self, template_id: int, material_type_code: str) -> None:
        super().__init__(
            f"Template {template_id} does not contain material type "
            f"'{material_type_code}'."
        )
        self.template_id = template_id
        self.material_type_code = material_type_code


class TemplateMaterialAlreadyExistsError(TemplateServiceError, ValueError):
    def __init__(self, template_id: int, material_type_code: str) -> None:
        super().__init__(
            f"Template {template_id} already contains material type "
            f"'{material_type_code}'."
        )
        self.template_id = template_id
        self.material_type_code = material_type_code


class TemplateNameAlreadyExistsError(TemplateServiceError, ValueError):
    def __init__(self, name: str) -> None:
        super().__init__(f"Template name '{name}' already exists.")
        self.name = name


class TemplateService:
    """Coordinate template use cases and their transaction boundaries."""

    def __init__(self, database: DatabaseManager) -> None:
        self._database = database

    def create_template(
        self, name: str, description: str | None = None
    ) -> Template:
        normalized_name = self._normalize_required_text(name, "name")
        normalized_description = self._normalize_optional_text(description)
        with self._database.transaction() as session:
            repository = TemplateRepository(session)
            if repository.get_by_name(normalized_name) is not None:
                raise TemplateNameAlreadyExistsError(normalized_name)
            template = repository.create(
                Template(
                    name=normalized_name,
                    description=normalized_description,
                )
            )
            return self._require_loaded_template(repository, template.id)

    def list_templates(self) -> list[Template]:
        with self._database.transaction() as session:
            return TemplateRepository(session).list_with_materials()

    def list_material_types(self) -> list[MaterialType]:
        """Return the existing material types available to template editors."""
        with self._database.transaction() as session:
            return MaterialTypeRepository(session).list()

    def get_template(self, template_id: int) -> Template:
        with self._database.transaction() as session:
            repository = TemplateRepository(session)
            return self._require_loaded_template(repository, template_id)

    def update_template(
        self,
        template_id: int,
        *,
        name: str,
        description: str | None = None,
    ) -> Template:
        normalized_name = self._normalize_required_text(name, "name")
        normalized_description = self._normalize_optional_text(description)
        with self._database.transaction() as session:
            repository = TemplateRepository(session)
            template = self._require_template(repository, template_id)
            duplicate = repository.get_by_name(normalized_name)
            if duplicate is not None and duplicate.id != template.id:
                raise TemplateNameAlreadyExistsError(normalized_name)
            template.name = normalized_name
            template.description = normalized_description
            repository.update(template)
            return self._require_loaded_template(repository, template.id)

    def delete_template(self, template_id: int) -> None:
        with self._database.transaction() as session:
            repository = TemplateRepository(session)
            template = self._require_template(repository, template_id)
            repository.delete(template)

    def add_material(
        self,
        template_id: int,
        material_type_code: str,
        *,
        required: bool = True,
        sort_order: int | None = None,
    ) -> TemplateMaterial:
        normalized_code = self._normalize_required_text(
            material_type_code, "material_type_code"
        )
        if sort_order is not None and sort_order < 0:
            raise ValueError("sort_order must be greater than or equal to zero")

        with self._database.transaction() as session:
            template_repository = TemplateRepository(session)
            self._require_template(template_repository, template_id)
            material_type = self._require_material_type(session, normalized_code)
            existing = template_repository.get_material(
                template_id, material_type.id
            )
            if existing is not None:
                raise TemplateMaterialAlreadyExistsError(
                    template_id, normalized_code
                )

            resolved_sort_order = sort_order
            if resolved_sort_order is None:
                materials = template_repository.list_materials(template_id)
                resolved_sort_order = (
                    max((value.sort_order for value in materials), default=0) + 1
                )

            template_material = template_repository.create_material(
                TemplateMaterial(
                    template_id=template_id,
                    material_type_id=material_type.id,
                    required=required,
                    sort_order=resolved_sort_order,
                )
            )
            template_material.material_type = material_type
            return template_material

    def remove_material(
        self, template_id: int, material_type_code: str
    ) -> None:
        normalized_code = self._normalize_required_text(
            material_type_code, "material_type_code"
        )
        with self._database.transaction() as session:
            repository = TemplateRepository(session)
            self._require_template(repository, template_id)
            material_type = self._require_material_type(session, normalized_code)
            template_material = repository.get_material(
                template_id, material_type.id
            )
            if template_material is None:
                raise TemplateMaterialNotFoundError(
                    template_id, normalized_code
                )
            repository.delete_material(template_material)

    def set_material_required(
        self,
        template_id: int,
        material_type_code: str,
        *,
        required: bool,
    ) -> TemplateMaterial:
        normalized_code = self._normalize_required_text(
            material_type_code, "material_type_code"
        )
        with self._database.transaction() as session:
            repository = TemplateRepository(session)
            self._require_template(repository, template_id)
            material_type = self._require_material_type(session, normalized_code)
            template_material = repository.get_material(
                template_id, material_type.id
            )
            if template_material is None:
                raise TemplateMaterialNotFoundError(
                    template_id, normalized_code
                )
            template_material.required = required
            repository.update_material(template_material)
            template_material.material_type = material_type
            return template_material

    def ensure_default_template(self) -> Template:
        """Create the default template once, preserving later user edits."""
        with self._database.transaction() as session:
            initialize_default_material_types(session)
            template_repository = TemplateRepository(session)
            existing = template_repository.get_by_name_with_materials(
                DEFAULT_TEMPLATE_NAME
            )
            if existing is not None:
                return existing

            template = template_repository.create(
                Template(
                    name=DEFAULT_TEMPLATE_NAME,
                    description=DEFAULT_TEMPLATE_DESCRIPTION,
                )
            )
            material_type_repository = MaterialTypeRepository(session)
            for sort_order, material_type_code in enumerate(
                DEFAULT_TEMPLATE_MATERIAL_CODES, start=1
            ):
                material_type = material_type_repository.get_by_code(
                    material_type_code
                )
                if material_type is None:
                    raise MaterialTypeNotFoundError(material_type_code)
                template_repository.create_material(
                    TemplateMaterial(
                        template_id=template.id,
                        material_type_id=material_type.id,
                        required=True,
                        sort_order=sort_order,
                    )
                )

            return self._require_loaded_template(template_repository, template.id)

    @staticmethod
    def _require_template(
        repository: TemplateRepository, template_id: int
    ) -> Template:
        template = repository.get_by_id(template_id)
        if template is None:
            raise TemplateNotFoundError(template_id)
        return template

    @staticmethod
    def _require_loaded_template(
        repository: TemplateRepository, template_id: int
    ) -> Template:
        template = repository.get_by_id_with_materials(template_id)
        if template is None:
            raise TemplateNotFoundError(template_id)
        return template

    @staticmethod
    def _require_material_type(
        session: Session, material_type_code: str
    ) -> MaterialType:
        material_type = MaterialTypeRepository(session).get_by_code(
            material_type_code
        )
        if material_type is None:
            raise MaterialTypeNotFoundError(material_type_code)
        return material_type

    @staticmethod
    def _normalize_required_text(value: str, field_name: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{field_name} cannot be blank")
        return normalized

    @staticmethod
    def _normalize_optional_text(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None
