"""Database abstraction layer with dialect-specific handling.

Provides a clean abstraction over SQLAlchemy engine creation and
dialect-specific operations to support both SQLite (dev) and PostgreSQL (prod).
"""

from contextlib import contextmanager
from enum import Enum
from typing import Any, Generator, Optional
from urllib.parse import urlparse

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DisconnectionError, OperationalError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import QueuePool

from app.core.config import settings


class DatabaseDialect(str, Enum):
    """Supported database dialects."""
    SQLITE = "sqlite"
    POSTGRESQL = "postgresql"
    MYSQL = "mysql"


class DatabaseError(Exception):
    """Base exception for database errors."""
    pass


class ConnectionError(DatabaseError):
    """Raised when database connection fails."""
    pass


class TransactionError(DatabaseError):
    """Raised when transaction operations fail."""
    pass


def _detect_dialect(db_url: str) -> DatabaseDialect:
    """Detect database dialect from URL."""
    parsed = urlparse(db_url)
    scheme = parsed.scheme.lower()

    if scheme.startswith("sqlite"):
        return DatabaseDialect.SQLITE
    elif scheme.startswith("postgresql") or scheme.startswith("postgres"):
        return DatabaseDialect.POSTGRESQL
    elif scheme.startswith("mysql"):
        return DatabaseDialect.MYSQL
    else:
        # Default to postgresql for unknown schemes
        return DatabaseDialect.POSTGRESQL


def _get_connect_args(dialect: DatabaseDialect) -> dict:
    """Get dialect-specific connect arguments."""
    if dialect == DatabaseDialect.SQLITE:
        return {"check_same_thread": False}
    elif dialect == DatabaseDialect.POSTGRESQL:
        return {
            "connect_timeout": 10,
            "application_name": settings.app_name,
        }
    elif dialect == DatabaseDialect.MYSQL:
        return {"connect_timeout": 10}
    return {}


def _get_engine_config(dialect: DatabaseDialect) -> dict:
    """Get dialect-specific engine configuration."""
    base_config = {
        "pool_pre_ping": True,  # Verify connections before use
    }

    if dialect == DatabaseDialect.SQLITE:
        # SQLite doesn't support connection pooling in the same way
        return {**base_config, "poolclass": None}

    elif dialect == DatabaseDialect.POSTGRESQL:
        return {
            **base_config,
            "poolclass": QueuePool,
            "pool_size": settings.db_pool_size,
            "max_overflow": settings.db_max_overflow,
            "pool_timeout": settings.db_pool_timeout,
            "pool_recycle": settings.db_pool_recycle,
        }

    elif dialect == DatabaseDialect.MYSQL:
        return {
            **base_config,
            "poolclass": QueuePool,
            "pool_size": settings.db_pool_size,
            "max_overflow": settings.db_max_overflow,
            "pool_timeout": settings.db_pool_timeout,
            "pool_recycle": settings.db_pool_recycle,
        }

    return base_config


def _setup_sqlite_pragmas(dbapi_connection, connection_record) -> None:
    """Set SQLite pragmas for better performance and integrity."""
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA cache_size=-32768")  # 32MB cache
        cursor.execute("PRAGMA temp_store=MEMORY")
        cursor.execute("PRAGMA mmap_size=268435456")  # 256MB mmap
    finally:
        cursor.close()


def _setup_postgresql_connection(dbapi_connection, connection_record) -> None:
    """Configure PostgreSQL connection settings."""
    cursor = dbapi_connection.cursor()
    try:
        # Set statement timeout to prevent runaway queries
        cursor.execute("SET statement_timeout = '30s'")
        # Set lock timeout
        cursor.execute("SET lock_timeout = '10s'")
        # Set idle transaction timeout
        cursor.execute("SET idle_in_transaction_session_timeout = '60s'")
    finally:
        cursor.close()


def _verify_connection(dbapi_connection, connection_record, connection_proxy) -> None:
    """Verify connection is still alive on checkout."""
    try:
        cursor = dbapi_connection.cursor()
        cursor.execute("SELECT 1")
        cursor.close()
    except Exception:
        raise DisconnectionError()


def create_engine_for_dialect(dialect: DatabaseDialect, db_url: str) -> Engine:
    """Create database engine with dialect-specific configuration."""
    connect_args = _get_connect_args(dialect)
    engine_config = _get_engine_config(dialect)

    engine = create_engine(db_url, connect_args=connect_args, **engine_config)

    # Add dialect-specific event listeners
    if dialect == DatabaseDialect.SQLITE:
        event.listen(engine, "connect", _setup_sqlite_pragmas)
    elif dialect == DatabaseDialect.POSTGRESQL:
        event.listen(engine, "connect", _setup_postgresql_connection)

    # Connection verification for pooled connections
    if dialect in (DatabaseDialect.POSTGRESQL, DatabaseDialect.MYSQL):
        event.listen(engine, "checkout", _verify_connection)

    return engine


def get_dialect() -> DatabaseDialect:
    """Get the current database dialect."""
    return _detect_dialect(settings.database_url)


def get_engine() -> Engine:
    """Create database engine with appropriate configuration for the database type."""
    dialect = get_dialect()
    return create_engine_for_dialect(dialect, settings.database_url)


# Create the engine
engine = get_engine()


# Session factory
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    """Database session dependency for FastAPI."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_db_context() -> Generator[Session, None, None]:
    """Context manager for database sessions outside of FastAPI."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    """Initialize database - create all tables."""
    from app import models
    Base.metadata.create_all(bind=engine)


def drop_db() -> None:
    """Drop all tables (use with caution!)."""
    Base.metadata.drop_all(bind=engine)


def get_pool_status() -> dict:
    """Get database connection pool status for monitoring."""
    if not hasattr(engine, 'pool') or engine.pool is None:
        return {
            "status": "no_pool",
            "message": "Engine does not have a pool (likely SQLite)",
            "dialect": get_dialect().value
        }

    pool = engine.pool
    pool_size = pool.size()
    checked_out = pool.checkedout()
    overflow = pool.overflow()
    max_overflow = pool._max_overflow if hasattr(pool, '_max_overflow') else 0
    total_available = pool_size + max_overflow

    # Calculate utilization
    utilization = (checked_out / total_available * 100) if total_available > 0 else 0

    # Determine status
    if utilization >= 90:
        status = "exhausted"
    elif utilization >= 75:
        status = "near_exhaustion"
    else:
        status = "ok"

    return {
        "status": status,
        "dialect": get_dialect().value,
        "pool_size": pool_size,
        "checked_in": pool.checkedin(),
        "checked_out": checked_out,
        "overflow": overflow,
        "max_overflow": max_overflow,
        "total_available": total_available,
        "utilization_percent": round(utilization, 2),
        "invalid": pool.invalidated(),
    }


def check_connectivity() -> tuple[bool, Optional[str]]:
    """Check database connectivity.

    Returns:
        Tuple of (is_healthy, error_message)
    """
    try:
        with get_db_context() as db:
            db.execute(text("SELECT 1"))
        return True, None
    except OperationalError as exc:
        return False, str(exc)
    except Exception as exc:
        return False, f"Unexpected error: {exc}"


# Dialect-specific query helpers

def get_for_update_clause(skip_locked: bool = True, nowait: bool = False) -> dict:
    """Get the appropriate FOR UPDATE clause options for the current dialect.

    Args:
        skip_locked: Skip locked rows (PostgreSQL, MySQL 8.0+)
        nowait: Don't wait for locks (PostgreSQL, MySQL, Oracle)

    Returns:
        Dictionary of options to pass to with_for_update()
    """
    dialect = get_dialect()

    if dialect == DatabaseDialect.SQLITE:
        # SQLite doesn't support FOR UPDATE SKIP LOCKED or NOWAIT
        return {}

    options = {}
    if skip_locked:
        options["skip_locked"] = True
    if nowait:
        options["nowait"] = True

    return options


def get_lock_wait_timeout() -> Optional[int]:
    """Get the lock wait timeout for the current dialect in seconds.

    Returns:
        Timeout in seconds, or None if not applicable
    """
    dialect = get_dialect()

    if dialect == DatabaseDialect.POSTGRESQL:
        return 10  # Set via SET lock_timeout in connection setup
    elif dialect == DatabaseDialect.MYSQL:
        return 10  # innodb_lock_wait_timeout
    return None


def is_serializable_isolation_supported() -> bool:
    """Check if SERIALIZABLE isolation level is supported."""
    dialect = get_dialect()
    return dialect in (DatabaseDialect.POSTGRESQL, DatabaseDialect.MYSQL)


def get_advisory_lock_function() -> Optional[str]:
    """Get the advisory lock function name for the current dialect.

    Returns:
        Function name for advisory locks, or None if not supported
    """
    dialect = get_dialect()

    if dialect == DatabaseDialect.POSTGRESQL:
        return "pg_advisory_xact_lock"
    elif dialect == DatabaseDialect.MYSQL:
        return "GET_LOCK"
    return None