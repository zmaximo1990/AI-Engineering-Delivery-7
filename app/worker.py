"""Background runners that execute / resume graph jobs and update Redis status."""

from __future__ import annotations

import logging
from typing import Any

from langgraph.types import Command

from app.agents.context import public_error
from app.decorators import task
from app.graph import final_answer_from_state, interrupts_from_state, run_config
from app.jobs import JobStatus
from app.state import initial_state

logger = logging.getLogger(__name__)

# Filled by FastAPI lifespan so @task callables can reach shared resources.
_APP_STATE: Any = None


def bind_app_state(state: Any) -> None:
    """Attach the FastAPI app.state used by background jobs."""
    global _APP_STATE
    _APP_STATE = state


def _require_state() -> Any:
    if _APP_STATE is None:
        raise RuntimeError("Worker app state is not bound. Start the API lifespan first.")
    return _APP_STATE


async def _finalize_or_pause(job_id: str, graph, config: dict) -> None:
    jobs = _require_state().jobs
    snapshot = await graph.aget_state(config)
    pending = interrupts_from_state(snapshot)
    if pending:
        await jobs.set_status(
            job_id,
            JobStatus.AWAITING_APPROVAL,
            interrupt=pending[0],
        )
        logger.info("Job %s awaiting human approval", job_id)
        return

    values = snapshot.values or {}
    answer = final_answer_from_state(values)
    await jobs.set_status(job_id, JobStatus.DONE, result=answer, interrupt="")
    logger.info("Job %s done", job_id)


@task
async def run_job(job_id: str) -> None:
    """Start a fresh graph run for ``job_id`` (fire-and-forget via ``@task``)."""
    state = _require_state()
    jobs = state.jobs
    graph = state.graph
    try:
        record = await jobs.get(job_id)
        if record is None:
            logger.error("Job %s missing from Redis", job_id)
            return
        question = record.get("question") or ""
        await jobs.set_status(job_id, JobStatus.RUNNING)
        config = run_config(job_id)
        await graph.ainvoke(initial_state(question), config)
        await _finalize_or_pause(job_id, graph, config)
    except Exception as exc:
        logger.exception("Job %s failed", job_id)
        await jobs.set_status(job_id, JobStatus.FAILED, error=public_error(exc))


@task
async def resume_job(job_id: str, *, approved: bool = True) -> None:
    """Resume a graph paused at the HITL gate."""
    state = _require_state()
    jobs = state.jobs
    graph = state.graph
    try:
        await jobs.set_status(job_id, JobStatus.RUNNING, interrupt="")
        config = run_config(job_id)
        await graph.ainvoke(Command(resume={"approved": approved}), config)
        await _finalize_or_pause(job_id, graph, config)
    except Exception as exc:
        logger.exception("Job %s resume failed", job_id)
        await jobs.set_status(job_id, JobStatus.FAILED, error=public_error(exc))
