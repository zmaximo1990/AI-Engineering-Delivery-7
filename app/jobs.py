"""Job status persistence in Redis (separate from LangGraph checkpoints)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from redis.asyncio import Redis

from app.settings import settings


class JobStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    DONE = "DONE"
    FAILED = "FAILED"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def job_key(job_id: str) -> str:
    return f"job:{job_id}"


class JobStore:
    """CRUD helpers for ``job:{id}`` hashes."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def create(self, job_id: str, question: str) -> dict[str, Any]:
        payload = {
            "job_id": job_id,
            "status": JobStatus.PENDING.value,
            "question": question,
            "result": "",
            "error": "",
            "interrupt": "",
            "created_at": _now(),
            "updated_at": _now(),
        }
        key = job_key(job_id)
        await self._redis.hset(key, mapping=payload)
        await self._redis.expire(key, settings.job_ttl_seconds)
        return payload

    async def get(self, job_id: str) -> dict[str, Any] | None:
        data = await self._redis.hgetall(job_key(job_id))
        if not data:
            return None
        return {k.decode() if isinstance(k, bytes) else k: (v.decode() if isinstance(v, bytes) else v) for k, v in data.items()}

    async def set_status(
        self,
        job_id: str,
        status: JobStatus,
        *,
        result: str | None = None,
        error: str | None = None,
        interrupt: dict[str, Any] | str | None = None,
    ) -> None:
        key = job_key(job_id)
        mapping: dict[str, str] = {
            "status": status.value,
            "updated_at": _now(),
        }
        if result is not None:
            mapping["result"] = result
        if error is not None:
            mapping["error"] = error
        if interrupt is not None:
            mapping["interrupt"] = (
                interrupt if isinstance(interrupt, str) else json.dumps(interrupt, ensure_ascii=False)
            )
        await self._redis.hset(key, mapping=mapping)
        await self._redis.expire(key, settings.job_ttl_seconds)

    async def ping(self) -> bool:
        return bool(await self._redis.ping())
