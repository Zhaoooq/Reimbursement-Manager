from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from reimbursement_manager.database.models import Template, TemplateMaterial
from reimbursement_manager.database.repositories.base import _Repository


class TemplateRepository(_Repository[Template]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, Template)

    def get_by_name(self, name: str) -> Template | None:
        statement = select(Template).where(Template.name == name)
        return self._session.scalar(statement)

    def get_by_id_with_materials(self, template_id: int) -> Template | None:
        statement = (
            select(Template)
            .where(Template.id == template_id)
            .options(
                selectinload(Template.materials).selectinload(
                    TemplateMaterial.material_type
                )
            )
        )
        template = self._session.scalar(statement)
        return self._sort_materials(template)

    def get_by_name_with_materials(self, name: str) -> Template | None:
        statement = (
            select(Template)
            .where(Template.name == name)
            .options(
                selectinload(Template.materials).selectinload(
                    TemplateMaterial.material_type
                )
            )
        )
        template = self._session.scalar(statement)
        return self._sort_materials(template)

    def list_with_materials(self) -> list[Template]:
        statement = (
            select(Template)
            .order_by(Template.id)
            .options(
                selectinload(Template.materials).selectinload(
                    TemplateMaterial.material_type
                )
            )
        )
        templates = list(self._session.scalars(statement))
        return [self._sort_materials(template) for template in templates]

    def get_material(
        self, template_id: int, material_type_id: int
    ) -> TemplateMaterial | None:
        statement = select(TemplateMaterial).where(
            TemplateMaterial.template_id == template_id,
            TemplateMaterial.material_type_id == material_type_id,
        )
        return self._session.scalar(statement)

    def list_materials(self, template_id: int) -> list[TemplateMaterial]:
        statement = (
            select(TemplateMaterial)
            .where(TemplateMaterial.template_id == template_id)
            .order_by(TemplateMaterial.sort_order, TemplateMaterial.id)
        )
        return list(self._session.scalars(statement))

    def create_material(self, entity: TemplateMaterial) -> TemplateMaterial:
        self._session.add(entity)
        self._session.flush()
        return entity

    def update_material(self, entity: TemplateMaterial) -> TemplateMaterial:
        self._session.add(entity)
        self._session.flush()
        return entity

    def delete_material(self, entity: TemplateMaterial) -> None:
        self._session.delete(entity)
        self._session.flush()

    @staticmethod
    def _sort_materials(template: Template | None) -> Template | None:
        if template is not None:
            template.materials.sort(key=lambda value: (value.sort_order, value.id))
        return template
