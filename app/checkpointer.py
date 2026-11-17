"""Checkpointer selected by ``CHECKPOINT_BACKEND``.

Redis (``AsyncRedisSaver``) is the default backend and needs Redis Stack
(RediSearch). ``sqlite`` (``AsyncSqliteSaver``) persists to
``settings.checkpoint_db_path``. ``memory`` is available for local smoke
tests without Redis indices. Register an async opener in ``_OPENERS`` and
allow its name in ``settings._CHECKPOINT_BACKENDS``.
"""

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.settings import settings

Opener = Callable[[], AbstractAsyncContextManager[BaseCheckpointSaver]]


@asynccontextmanager
async def _open_redis() -> AsyncIterator[BaseCheckpointSaver]:
    """Open AsyncRedisSaver against ``settings.redis_url`` and create indices."""
    try:
        from langgraph.checkpoint.redis.aio import AsyncRedisSaver
    except ImportError:  # pragma: no cover - package layout variants
        from langgraph.checkpoint.redis import AsyncRedisSaver

    async with AsyncRedisSaver.from_conn_string(settings.redis_url) as saver:
        setup = getattr(saver, "asetup", None) or getattr(saver, "setup")
        result = setup()
        if hasattr(result, "__await__"):
            await result
        yield saver


@asynccontextmanager
async def _open_sqlite() -> AsyncIterator[BaseCheckpointSaver]:
    """Open the SQLite file at ``settings.checkpoint_db_path`` and create its tables."""
    settings.checkpoint_db_path.parent.mkdir(parents=True, exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(str(settings.checkpoint_db_path)) as saver:
        await saver.setup()
        yield saver


@asynccontextmanager
async def _open_memory() -> AsyncIterator[BaseCheckpointSaver]:
    """In-process saver. Lost on process restart; useful without Redis Stack."""
    yield MemorySaver()


_OPENERS: dict[str, Opener] = {
    "redis": _open_redis,
    "sqlite": _open_sqlite,
    "memory": _open_memory,
}


@asynccontextmanager
async def open_checkpointer() -> AsyncIterator[BaseCheckpointSaver]:
    """Open the saver named by ``settings.checkpoint_backend``."""
    opener = _OPENERS.get(settings.checkpoint_backend)
    if opener is None:
        allowed = ", ".join(sorted(_OPENERS))
        raise ValueError(f"CHECKPOINT_BACKEND must be one of: {allowed}")
    async with opener() as saver:
        yield saver
