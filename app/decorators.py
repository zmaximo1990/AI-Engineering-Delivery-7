"""Background task dispatch helpers."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from functools import wraps
from typing import Any, ParamSpec, TypeVar

logger = logging.getLogger(__name__)

P = ParamSpec("P")
R = TypeVar("R")


def task(fn: Callable[P, Coroutine[Any, Any, R]]) -> Callable[P, asyncio.Task[R]]:
    """Schedule ``fn`` on the running event loop (``asyncio.create_task``).

    Swap path to Celery (not wired in this delivery):
    - Replace this body with a Celery ``shared_task`` / ``apply_async`` wrapper
      (or decorate ``run_job`` / ``resume_job`` with ``@celery_app.task`` and
      call ``.delay(job_id)`` from the endpoints).
    - Add a ``celery-worker`` service to ``docker-compose.yml`` that runs
      ``celery -A app.worker worker`` against the same Redis broker
      (see the commented block in that file).
    - Keep ``run_job(job_id)`` / ``resume_job(job_id)`` signatures stable so
      endpoints stay ``run_job(job_id)`` without caring who executes them.
    """

    @wraps(fn)
    def enqueue(*args: P.args, **kwargs: P.kwargs) -> asyncio.Task[R]:
        scheduled = asyncio.create_task(fn(*args, **kwargs))

        def _log_done(done: asyncio.Task[R]) -> None:
            try:
                done.result()
            except asyncio.CancelledError:
                logger.info("Background task cancelled: %s", fn.__name__)
            except Exception:
                logger.exception("Background task failed: %s", fn.__name__)

        scheduled.add_done_callback(_log_done)
        return scheduled

    return enqueue
