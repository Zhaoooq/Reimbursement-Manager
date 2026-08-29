from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, URL, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


def _enable_sqlite_foreign_keys(
    dbapi_connection: Any, connection_record: Any
) -> None:
    """Enable SQLite foreign-key enforcement for one DB-API connection."""
    del connection_record
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


def _configure_sqlite_engine(engine: Engine) -> Engine:
    event.listen(engine, "connect", _enable_sqlite_foreign_keys)
    return engine


class DatabaseManager:
    """Own a database engine, session factory, and transaction lifecycle."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._session_factory = sessionmaker(
            bind=engine,
            class_=Session,
            expire_on_commit=False,
        )

    @classmethod
    def from_sqlite_path(
        cls, database_path: Path, *, echo: bool = False
    ) -> "DatabaseManager":
        """Create a manager for a file-backed SQLite database."""
        resolved_path = Path(database_path).expanduser().resolve()
        resolved_path.parent.mkdir(parents=True, exist_ok=True)
        url = URL.create("sqlite+pysqlite", database=str(resolved_path))
        engine = create_engine(url, echo=echo)
        return cls(_configure_sqlite_engine(engine))

    @classmethod
    def in_memory(cls, *, echo: bool = False) -> "DatabaseManager":
        """Create a manager backed by one shared in-memory SQLite database."""
        engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            echo=echo,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        return cls(_configure_sqlite_engine(engine))

    @property
    def engine(self) -> Engine:
        return self._engine

    @property
    def session_factory(self) -> sessionmaker[Session]:
        return self._session_factory

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        """Yield a fresh session and commit or roll back as one unit of work."""
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def dispose(self) -> None:
        """Release connections owned by this manager's engine."""
        self._engine.dispose()
