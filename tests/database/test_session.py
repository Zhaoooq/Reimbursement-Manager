from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from reimbursement_manager.database import DatabaseManager


def test_file_database_supports_unicode_paths_and_foreign_keys(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "中文 数据" / "app.db"
    manager = DatabaseManager.from_sqlite_path(database_path)

    try:
        with manager.transaction() as session:
            foreign_keys_enabled = session.scalar(text("PRAGMA foreign_keys"))

        assert database_path.is_file()
        assert foreign_keys_enabled == 1
    finally:
        manager.dispose()


def test_session_factory_creates_distinct_sessions() -> None:
    manager = DatabaseManager.in_memory()

    first = manager.session_factory()
    second = manager.session_factory()
    try:
        assert isinstance(first, Session)
        assert isinstance(second, Session)
        assert first is not second
    finally:
        first.close()
        second.close()
        manager.dispose()


def test_transaction_commits_successful_work() -> None:
    manager = DatabaseManager.in_memory()

    try:
        with manager.transaction() as session:
            session.execute(text("CREATE TABLE entries (value TEXT NOT NULL)"))

        with manager.transaction() as session:
            session.execute(
                text("INSERT INTO entries (value) VALUES (:value)"),
                {"value": "saved"},
            )

        with manager.transaction() as session:
            saved_value = session.scalar(text("SELECT value FROM entries"))

        assert saved_value == "saved"
    finally:
        manager.dispose()


def test_transaction_rolls_back_and_reraises_errors() -> None:
    manager = DatabaseManager.in_memory()

    try:
        with manager.transaction() as session:
            session.execute(text("CREATE TABLE entries (value TEXT NOT NULL)"))

        with pytest.raises(RuntimeError, match="force rollback"):
            with manager.transaction() as session:
                session.execute(
                    text("INSERT INTO entries (value) VALUES (:value)"),
                    {"value": "discarded"},
                )
                raise RuntimeError("force rollback")

        with manager.transaction() as session:
            row_count = session.scalar(text("SELECT COUNT(*) FROM entries"))

        assert row_count == 0
    finally:
        manager.dispose()


def test_in_memory_database_is_shared_across_transactions() -> None:
    manager = DatabaseManager.in_memory()

    try:
        with manager.transaction() as session:
            session.execute(text("CREATE TABLE marker (id INTEGER PRIMARY KEY)"))
            session.execute(text("INSERT INTO marker (id) VALUES (1)"))

        with manager.transaction() as session:
            marker_id = session.scalar(text("SELECT id FROM marker"))

        assert marker_id == 1
    finally:
        manager.dispose()
