import logging
from collections.abc import AsyncGenerator, Callable

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.telemetry import instrument_engine

logger = logging.getLogger(__name__)
_AFTER_COMMIT = "after_commit_callbacks"


def run_after_commit(session: AsyncSession, callback: Callable[[], None]) -> None:
    """Run `callback` once the current transaction commits; dropped on rollback.

    Use for side effects others must not observe before the data is visible (task enqueue).
    """
    session.sync_session.info.setdefault(_AFTER_COMMIT, []).append(callback)


@event.listens_for(Session, "after_commit")
def _run_after_commit(session: Session) -> None:
    for callback in session.info.pop(_AFTER_COMMIT, []):
        try:
            callback()
        except Exception:
            logger.exception("after_commit_callback_failed")


@event.listens_for(Session, "after_rollback")
def _drop_after_commit(session: Session) -> None:
    session.info.pop(_AFTER_COMMIT, None)


def create_engine(settings: Settings) -> AsyncEngine:
    engine = create_async_engine(
        settings.database_url,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_timeout=settings.database_pool_timeout_seconds,
        pool_recycle=settings.database_pool_recycle_seconds,
        pool_pre_ping=True,
        echo=settings.database_echo,
    )
    instrument_engine(engine, settings)
    return engine


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


async def session_scope(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession]:
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
