"""Database engine / session helpers.

The engine is built from a URL (not created at import time against a real
server) so tests can inject an in-memory SQLite engine cleanly. The app wires
its engine and sessionmaker onto ``app.state`` in the application factory.
"""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool


class Base(DeclarativeBase):
    pass


def make_engine(url: str) -> Engine:
    connect_args: dict = {}
    kwargs: dict = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        if ":memory:" in url:
            # Keep one shared connection so in-memory data survives across
            # sessions within a test process.
            kwargs["poolclass"] = StaticPool
    return create_engine(url, future=True, connect_args=connect_args, **kwargs)


def make_sessionmaker(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        class_=Session,
        future=True,
    )
