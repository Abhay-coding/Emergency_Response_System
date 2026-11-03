from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session
from sqlalchemy.pool import QueuePool

from app.core.config import settings


def get_engine():
    """Create database engine with appropriate configuration for the database type"""
    db_url = settings.database_url

    # Common connect args
    connect_args = {}

    if db_url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
        engine = create_engine(
            db_url,
            connect_args=connect_args,
            # SQLite doesn't support connection pooling in the same way
        )
    elif db_url.startswith("postgresql"):
        # PostgreSQL with connection pooling for RDS
        engine = create_engine(
            db_url,
            poolclass=QueuePool,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_timeout=settings.db_pool_timeout,
            pool_recycle=settings.db_pool_recycle,
            pool_pre_ping=True,  # Verify connections before use
            connect_args=connect_args,
        )
    else:
        # Default for other databases
        engine = create_engine(
            db_url,
            connect_args=connect_args,
        )

    # Add event listeners for connection handling
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        """Set SQLite pragmas for better performance and integrity"""
        if db_url.startswith("sqlite"):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA cache_size=-32768")  # 32MB cache
            cursor.close()

    @event.listens_for(engine, "checkout")
    def ping_connection(dbapi_connection, connection_record, connection_proxy):
        """Verify connection is still alive on checkout"""
        if db_url.startswith("postgresql"):
            try:
                cursor = dbapi_connection.cursor()
                cursor.execute("SELECT 1")
                cursor.close()
            except Exception:
                # Connection is dead, raise DisconnectionError
                from sqlalchemy.exc import DisconnectionError
                raise DisconnectionError()

    return engine


engine = get_engine()


SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,  # Don't expire objects after commit
)


class Base(DeclarativeBase):
    pass


def get_db() -> Session:
    """Database session dependency"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Initialize database - create all tables"""
    from app import models
    Base.metadata.create_all(bind=engine)


def drop_db() -> None:
    """Drop all tables (use with caution!)"""
    Base.metadata.drop_all(bind=engine)