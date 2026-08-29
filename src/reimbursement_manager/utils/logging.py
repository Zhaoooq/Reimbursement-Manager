import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


_HANDLER_MARKER = "reimbursement_manager_managed"


def configure_logging(
    log_dir: Path,
    *,
    logger_name: str = "reimbursement_manager",
    level: int = logging.INFO,
) -> logging.Logger:
    """Configure console and rotating-file logging once for a named logger."""
    resolved_log_dir = Path(log_dir).expanduser().resolve()
    resolved_log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(logger_name)
    logger.setLevel(level)
    logger.propagate = False

    if any(getattr(handler, _HANDLER_MARKER, False) for handler in logger.handlers):
        return logger

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    setattr(console_handler, _HANDLER_MARKER, True)

    file_handler = RotatingFileHandler(
        resolved_log_dir / "reimbursement_manager.log",
        maxBytes=2 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    setattr(file_handler, _HANDLER_MARKER, True)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    return logger


def shutdown_logging(logger: logging.Logger) -> None:
    """Flush, close, and detach handlers managed by this application."""
    managed_handlers = (
        handler
        for handler in tuple(logger.handlers)
        if getattr(handler, _HANDLER_MARKER, False)
    )
    for handler in managed_handlers:
        logger.removeHandler(handler)
        handler.flush()
        handler.close()
