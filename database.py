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
    """Create all tables. Safe to call multiple times."""
    import models  # noqa: F401 — ensures models are registered with Base
    Base.metadata.create_all(bind=engine)
