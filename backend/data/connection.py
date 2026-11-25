"""Small compatibility layer for the existing storage SQL.

The application historically used sqlite3-style ``?`` parameters and rows
addressable by column name.  This adapter keeps that public storage contract
while using SQLAlchemy's PostgreSQL engine and pool in normal application
execution.
"""

from __future__ import annotations

import re
from threading import Lock
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import create_engine
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import SQLAlchemyError

from config import (
    DB_CONNECT_TIMEOUT_SECONDS,
    DB_MAX_OVERFLOW,
    DB_POOL_RECYCLE_SECONDS,
    DB_POOL_SIZE,
)


class _Row(dict[str, Any]):
    """Mapping row that also preserves the old ``row[0]`` behavior."""

    def __getitem__(self, key: str | int) -> Any:
        if isinstance(key, int):
            return tuple(self.values())[key]
        return super().__getitem__(key)


class _Result:
    def __init__(self, result: Any) -> None:
        self._result = result
        self._has_rows = bool(getattr(result, "returns_rows", False))
        self._keys = list(result.keys()) if self._has_rows else []

    def _row(self, value: Any) -> _Row | None:
        if value is None:
            return None
        return _Row(zip(self._keys, value))

    def fetchone(self) -> _Row | None:
        if not self._has_rows:
            return None
        return self._row(self._result.fetchone())

    def fetchall(self) -> list[_Row]:
        if not self._has_rows:
            return []
        return [self._row(value) for value in self._result.fetchall()]


class PostgresConnection:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def execute(
        self,
        statement: str,
        parameters: Any = (),
    ) -> _Result:
        sql = re.sub(r"\?", "%s", statement)
        sql = re.sub(
            r"INSERT\s+OR\s+IGNORE\s+INTO",
            "INSERT INTO",
            sql,
            flags=re.IGNORECASE,
        )
        if re.search(r"INSERT\s+INTO", statement, flags=re.IGNORECASE) and re.search(
            r"INSERT\s+OR\s+IGNORE", statement, flags=re.IGNORECASE
        ):
            sql = sql.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
        sql = re.sub(
            r"INTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT",
            "BIGSERIAL PRIMARY KEY",
            sql,
            flags=re.IGNORECASE,
        )
        if isinstance(parameters, list):
            parameters = tuple(parameters)
        try:
            if parameters in (None, ()):
                result = self._connection.exec_driver_sql(sql)
            else:
                result = self._connection.exec_driver_sql(sql, parameters)
        except SQLAlchemyError as error:
            raise RuntimeError(
                "PostgreSQL query failed. Check the schema and DATABASE_URL."
            ) from error
        return _Result(result)

    def commit(self) -> None:
        self._connection.commit()

    def rollback(self) -> None:
        self._connection.rollback()

    def close(self) -> None:
        self._connection.close()


_engines: dict[str, Engine] = {}
_engines_lock = Lock()


def get_engine(database_url: str) -> Engine:
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL is required. ClaimGuard will not fall back to SQLite."
        )

    normalized_url = database_url
    if normalized_url.startswith("postgres://"):
        normalized_url = "postgresql+psycopg://" + normalized_url[len("postgres://"):]
    elif normalized_url.startswith("postgresql://"):
        normalized_url = "postgresql+psycopg://" + normalized_url[len("postgresql://"):]

    with _engines_lock:
        engine = _engines.get(normalized_url)
        if engine is None:
            engine = create_engine(
                normalized_url,
                pool_pre_ping=True,
                pool_size=DB_POOL_SIZE,
                max_overflow=DB_MAX_OVERFLOW,
                pool_recycle=DB_POOL_RECYCLE_SECONDS,
                connect_args={"connect_timeout": DB_CONNECT_TIMEOUT_SECONDS},
            )
            _engines[normalized_url] = engine
        return engine


def connect_postgres(database_url: str) -> PostgresConnection:
    parsed = urlsplit(database_url)
    expected_database = parsed.path.lstrip("/").split("?", 1)[0]
    if not expected_database:
        raise RuntimeError("DATABASE_URL must include a PostgreSQL database name.")

    connection = None
    try:
        connection = PostgresConnection(get_engine(database_url).connect())
        actual_database = connection.execute(
            "SELECT current_database()"
        ).fetchone()
        if not actual_database or actual_database[0] != expected_database:
            raise RuntimeError(
                "PostgreSQL connection identity does not match DATABASE_URL."
            )
        return connection
    except SQLAlchemyError as error:
        if connection is not None:
            connection.close()
        raise RuntimeError(
            "Unable to connect to PostgreSQL. Check DATABASE_URL and server readiness."
        ) from error
    except Exception:
        if connection is not None:
            connection.close()
        raise
