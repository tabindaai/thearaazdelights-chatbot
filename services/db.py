
"""
PostgreSQL database connection and session management.

Supports DATABASE_URL or separate DB_* environment variables.
If neither is configured, the application can use its mock backend.
"""

import logging
import os
from typing import Generator, Optional

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, URL
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

load_dotenv()

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """Base class for SQLAlchemy database models."""
    pass


def build_database_url():
    """Build a database URL from available environment settings."""

    database_url = os.getenv("DATABASE_URL", "").strip()

    if database_url:
        return database_url

    db_user = os.getenv("DB_USER")
    db_password = os.getenv("DB_PASSWORD")
    db_host = os.getenv("DB_HOST")
    db_port = os.getenv("DB_PORT", "5432")
    db_name = os.getenv("DB_NAME")

    if all([db_user, db_password, db_host, db_name]):
        return URL.create(
            drivername="postgresql+psycopg",
            username=db_user,
            password=db_password,
            host=db_host,
            port=int(db_port),
            database=db_name,
        )

    return None


DATABASE_URL = build_database_url()

engine: Optional[Engine] = None
SessionLocal: Optional[sessionmaker] = None

if DATABASE_URL:
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
    )

    SessionLocal = sessionmaker(
        bind=engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )

    logger.info("PostgreSQL database engine configured.")
else:
    logger.info(
        "Database configuration missing. "
        "The application can use its mock backend."
    )


def is_database_configured() -> bool:
    """Return whether PostgreSQL is configured."""
    return engine is not None and SessionLocal is not None


def get_db() -> Generator[Session, None, None]:
    """Provide a database session and close it afterward."""

    if SessionLocal is None:
        raise RuntimeError(
            "Database is not configured. Check your environment settings."
        )

    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()
