"""FastAPI entrypoint: enqueue tasks, poll status, approve HITL pauses."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from redis.asyncio import Redis

from app.checkpointer import open_checkpointer
from app.graph import compile_graph
from app.jobs import JobStatus, JobStore
from app.observability import setup_observability
from app.schemas import LLMConfig, LLMProvider
from app.settings import settings
from app.worker import bind_app_state, resume_job, run_job

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


# DTO for asking
class TaskCreate(BaseModel):
    question: str = Field(..., min_length=1)

# DTO for the task created
class TaskCreated(BaseModel):
    job_id: str
    status: str

# DTO for the task view
class TaskView(BaseModel):
    job_id: str
    status: str
    question: str = ""
    result: str = ""
    error: str = ""
    interrupt: str = ""
    created_at: str = ""
    updated_at: str = ""


# DTO for the approve body
class ApproveBody(BaseModel):
    approved: bool = True


@asynccontextmanager
async def lifespan(app: FastAPI):
    tracer = setup_observability()
    redis = Redis.from_url(settings.redis_url, decode_responses=False)
    jobs = JobStore(redis)
    provider = LLMProvider(settings.default_provider)
    config = LLMConfig(provider=provider)

    async with open_checkpointer() as checkpointer:
        graph = compile_graph(config, checkpointer)
        app.state.redis = redis
        app.state.jobs = jobs
        app.state.graph = graph
        app.state.tracer = tracer
        bind_app_state(app.state)
        logger.info(
            "API ready provider=%s checkpoint=%s observability=%s",
            provider.value,
            settings.checkpoint_backend,
            settings.observability_provider,
        )
        try:
            yield
        finally:
            bind_app_state(None)
            tracer.shutdown()
            await redis.aclose()


app = FastAPI(title="delivery7 multi-agent API", lifespan=lifespan)


@app.get("/health")
async def health(request: Request) -> dict[str, Any]:
    jobs: JobStore = request.app.state.jobs
    try:
        ok = await jobs.ping()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"redis unavailable: {exc}") from exc
    return {
        "status": "ok" if ok else "degraded",
        "redis": ok,
        "observability": settings.observability_provider,
        "checkpoint": settings.checkpoint_backend,
    }


@app.post("/tasks", response_model=TaskCreated, status_code=201)
async def create_task(body: TaskCreate, request: Request) -> TaskCreated:
    """Enqueue a job and return immediately with a job_id."""
    jobs: JobStore = request.app.state.jobs
    job_id = str(uuid4())
    await jobs.create(job_id, body.question.strip())
    run_job(job_id)
    return TaskCreated(job_id=job_id, status=JobStatus.PENDING.value)


@app.get("/tasks/{job_id}", response_model=TaskView)
async def get_task(job_id: str, request: Request) -> TaskView:
    jobs: JobStore = request.app.state.jobs
    record = await jobs.get(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="job not found")
    return TaskView(**record)


@app.post("/tasks/{job_id}/approve", response_model=TaskView)
async def approve_task(job_id: str, request: Request, body: ApproveBody | None = None) -> TaskView:
    """Resume a graph paused at the HITL research gate."""
    jobs: JobStore = request.app.state.jobs
    record = await jobs.get(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="job not found")
    if record.get("status") != JobStatus.AWAITING_APPROVAL.value:
        raise HTTPException(
            status_code=409,
            detail=f"job status is {record.get('status')}, expected AWAITING_APPROVAL",
        )
    approved = True if body is None else body.approved
    resume_job(job_id, approved=approved)
    record = await jobs.get(job_id) or record
    # Status flips to RUNNING asynchronously; return current snapshot.
    return TaskView(**record)
