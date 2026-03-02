from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

import config

# Only pass check_same_thread for SQLite (PostgreSQL doesn't need it)
connect_args = {}
if config.DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(
    config.DATABASE_URL,
    connect_args=connect_args,
    echo=False,
    pool_pre_ping=True,  # Reconnect on stale connections (important for PostgreSQL)
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """FastAPI dependency that yields a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables and run lightweight migrations."""
    import models  # noqa: F401 — ensures models are registered with Base
    Base.metadata.create_all(bind=engine)

    # Add columns that may be missing from earlier schema versions.
    _add_column_if_missing("leads", "bison_reply_id", "INTEGER")
    _add_column_if_missing("leads", "bison_sender_email_id", "INTEGER")


def _add_column_if_missing(table: str, column: str, col_type: str):
    """Add a column to an existing table if it doesn't exist yet."""
    from sqlalchemy import text, inspect
    insp = inspect(engine)
    existing = [c["name"] for c in insp.get_columns(table)]
    if column not in existing:
        with engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))

