"""Human-in-the-loop gate before side-effect / high-cost research tools."""

from __future__ import annotations

from typing import Any

from langgraph.types import interrupt

from app.state import OrchestratorState


def hitl_gate_node(state: OrchestratorState) -> dict[str, Any]:
    """Pause before ``researcher`` until ``POST /tasks/{id}/approve`` resumes.

    ``web_search`` (Tavily) is treated as the critical side-effect tool: it
    incurs external cost and leaves the local process. The interrupt payload is
    stored on the job so the client can show what is waiting for approval.
    """
    decision = interrupt(
        {
            "type": "approve_research",
            "reason": "Research uses web_search (external side effect / cost).",
            "instruction": state.get("instruction") or "",
            "question": _question_from_state(state),
        }
    )
    if isinstance(decision, dict) and decision.get("approved") is False:
        return {
            "last_error": "Human rejected the research step.",
            "next_agent": "synthesizer",
        }
    return {}


def _question_from_state(state: OrchestratorState) -> str:
    messages = state.get("messages") or []
    for message in messages:
        content = getattr(message, "content", None)
        if isinstance(content, str) and content.strip():
            return content.strip()
    return ""
