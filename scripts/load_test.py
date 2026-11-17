#!/usr/bin/env python3
"""Launch 5 concurrent tasks against the API and auto-approve HITL pauses.

Uses a fixed question (repeated) so cost / latency are comparable across the run.
"""

from __future__ import annotations

import argparse
import asyncio
import time
from typing import Any

import httpx

# Same shape as delivery6 sample sentiment question — fixed, not random.
FIXED_QUESTION = (
    "Busca cobertura reciente de los últimos resultados trimestrales de NVIDIA "
    "y puntúa el sentimiento general de esas fuentes."
)


async def poll_until_done(
    client: httpx.AsyncClient,
    job_id: str,
    *,
    timeout_s: float,
    interval_s: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        response = await client.get(f"/tasks/{job_id}")
        response.raise_for_status()
        payload = response.json()
        status = payload.get("status")
        if status == "AWAITING_APPROVAL":
            approve = await client.post(f"/tasks/{job_id}/approve", json={"approved": True})
            approve.raise_for_status()
        elif status in {"DONE", "FAILED"}:
            return payload
        await asyncio.sleep(interval_s)
    raise TimeoutError(f"job {job_id} did not finish within {timeout_s}s")


async def run_one(client: httpx.AsyncClient, index: int, question: str, timeout_s: float) -> dict[str, Any]:
    started = time.perf_counter()
    created = await client.post("/tasks", json={"question": question})
    created.raise_for_status()
    job_id = created.json()["job_id"]
    final = await poll_until_done(client, job_id, timeout_s=timeout_s, interval_s=1.0)
    elapsed = time.perf_counter() - started
    return {
        "index": index,
        "job_id": job_id,
        "status": final.get("status"),
        "elapsed_s": round(elapsed, 2),
        "error": final.get("error") or "",
        "result_chars": len(final.get("result") or ""),
    }


async def main_async(base_url: str, n: int, timeout_s: float) -> None:
    questions = [FIXED_QUESTION] * n
    async with httpx.AsyncClient(base_url=base_url, timeout=60.0) as client:
        health = await client.get("/health")
        health.raise_for_status()
        print("health:", health.json())
        started = time.perf_counter()
        results = await asyncio.gather(
            *[run_one(client, i + 1, q, timeout_s) for i, q in enumerate(questions)],
            return_exceptions=True,
        )
        wall = time.perf_counter() - started

    print(f"\nwall_clock_s={wall:.2f} concurrent={n}")
    ok = 0
    for item in results:
        if isinstance(item, Exception):
            print("ERROR", repr(item))
            continue
        print(item)
        if item.get("status") == "DONE":
            ok += 1
    print(f"done={ok}/{n}")
    print(
        "Capture cost-per-run and p95 latency from the observability dashboard "
        "(LangSmith by default, or Phoenix at http://localhost:6006) into screenshots/."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("-n", type=int, default=5, help="Concurrent requests (default 5)")
    parser.add_argument("--timeout", type=float, default=600.0, help="Per-job timeout seconds")
    args = parser.parse_args()
    asyncio.run(main_async(args.base_url, args.n, args.timeout))


if __name__ == "__main__":
    main()
