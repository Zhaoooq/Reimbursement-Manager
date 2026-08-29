"""Run a small, isolated Phase 1 reimbursement workflow demonstration."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from reimbursement_manager.database import (
    DatabaseManager,
    initialize_default_material_types,
    upgrade_database,
)
from reimbursement_manager.database.models import ReimbursementBatch
from reimbursement_manager.database.repositories import (
    BatchRepository,
    MaterialTypeRepository,
)
from reimbursement_manager.domain import ReimbursementStatus
from reimbursement_manager.services import (
    AttachmentService,
    CompletenessResult,
    CompletenessService,
    ItemService,
    StoragePathService,
    TemplateService,
)


def _material_type_id(database: DatabaseManager, code: str) -> int:
    with database.transaction() as session:
        material_type = MaterialTypeRepository(session).get_by_code(code)
        if material_type is None:
            raise RuntimeError(f"Default material type '{code}' was not seeded.")
        return material_type.id


def _print_summary(
    *, item_name: str, result: CompletenessResult, workspace: Path
) -> None:
    print("Item:")
    print(item_name)
    print()
    print(f"Required: {result.required_count}")
    print(f"Completed: {result.completed_count}")
    print("Missing:")
    for material in result.missing:
        print(f"- {material.name}")
    print()
    print(f"Completeness: {result.percentage}%")
    print(f"Workspace: {workspace}")


def run_demo(workspace: Path) -> CompletenessResult:
    """Create an incomplete example item and print its material summary."""
    resolved_workspace = Path(workspace).expanduser().resolve()
    database_path = resolved_workspace / "data" / "demo.db"
    archive_root = resolved_workspace / "archive"
    source_directory = resolved_workspace / "source-files"
    source_directory.mkdir(parents=True, exist_ok=True)

    upgrade_database(project_root=PROJECT_ROOT, database_path=database_path)
    database = DatabaseManager.from_sqlite_path(database_path)
    try:
        with database.transaction() as session:
            initialize_default_material_types(session)

        template = TemplateService(database).ensure_default_template()
        batch_name = f"Phase 1 演示报销 {datetime.now():%Y%m%d-%H%M%S-%f}"
        with database.transaction() as session:
            batch = BatchRepository(session).create(
                ReimbursementBatch(
                    name=batch_name,
                    status=ReimbursementStatus.COLLECTING,
                )
            )
            batch_id = batch.id

        item_name = "树莓派 Zero 2 W"
        item = ItemService(database).create_item(
            batch_id=batch_id,
            template_id=template.id,
            sequence_number=1,
            name=item_name,
            total_amount_cents=0,
        )
        storage = StoragePathService(archive_root)
        attachment_service = AttachmentService(database, storage)

        for material_code, filename in (
            ("physical_photo", "实物照片.jpg"),
            ("payment_screenshot", "支付截图.png"),
            ("order_screenshot", "订单截图.png"),
        ):
            source_path = source_directory / filename
            source_path.write_bytes(material_code.encode("utf-8"))
            attachment_service.add_attachment(
                item_id=item.id,
                material_type_id=_material_type_id(database, material_code),
                source_path=source_path,
            )

        result = CompletenessService(database, storage).calculate(item.id)
        _print_summary(
            item_name=item_name,
            result=result,
            workspace=resolved_workspace,
        )
        return result
    finally:
        database.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run an isolated Phase 1 reimbursement workflow demo."
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=PROJECT_ROOT / "data" / "phase1-demo",
        help="Directory for demo-only database, source files, and archive.",
    )
    arguments = parser.parse_args(argv)
    run_demo(arguments.workspace)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
