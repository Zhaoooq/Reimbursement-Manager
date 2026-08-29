import logging
from pathlib import Path

from reimbursement_manager.utils.logging import configure_logging, shutdown_logging


def test_configure_logging_is_idempotent(tmp_path: Path) -> None:
    logger_name = "reimbursement_manager.test"

    first = configure_logging(tmp_path, logger_name=logger_name)
    try:
        second = configure_logging(tmp_path, logger_name=logger_name)

        assert first is second
        assert first.level == logging.INFO
        assert len(first.handlers) == 2
        assert (tmp_path / "reimbursement_manager.log").exists()
    finally:
        shutdown_logging(first)
