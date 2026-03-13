"""Database session helper for the worker process."""

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://voice:voice@db:5432/voice",
)

_engine = None


def get_db_session() -> Session:
    """Get a new database session for pipeline use."""
    global _engine
    if _engine is None:
        _engine = create_engine(DATABASE_URL)
    return Session(_engine)
