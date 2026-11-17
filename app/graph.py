"""Hierarchical StateGraph: supervisor, HITL gate, researcher, analyst, validator, synthesizer."""

from __future__ import annotations

import logging
from typing import Literal

from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agents.analyst_agent import make_analyst_node
from app.agents.research_agent import make_research_node
from app.agents.supervisor import make_supervisor_node
from app.agents.synthesizer import make_synthesizer_node
from app.agents.validator import validator_node
from app.factory import LLMFactory
from app.hitl import hitl_gate_node
from app.schemas import LLMConfig
from app.settings import settings
from app.state import OrchestratorState

logger = logging.getLogger(__name__)

SupervisorRoute = Literal["hitl_gate", "analyst", "validator", "synthesizer"]
ValidatorRoute = Literal["supervisor", "synthesizer"]


def route_from_supervisor(state: OrchestratorState) -> SupervisorRoute:
    """Conditional edge. Research goes through HITL; the step cap exits via synthesizer."""
    if int(state.get("step_count") or 0) >= settings.max_supervisor_steps:
        return "synthesizer"
    next_agent = state.get("next_agent") or "researcher"
    if next_agent == "researcher":
        return "hitl_gate"
    if next_agent in {"analyst", "validator"}:
        return next_agent  # type: ignore[return-value]
    return "hitl_gate"


def route_from_validator(state: OrchestratorState) -> ValidatorRoute:
    """Approved work is synthesized. A rejection returns to the supervisor while a retry is still possible."""
    if state.get("validation_passed"):
        return "synthesizer"
    if int(state.get("step_count") or 0) >= settings.max_supervisor_steps:
        return "synthesizer"

    feedback = (state.get("validation_feedback") or "").lower()
    research_runs = int(state.get("research_runs") or 0)
    analyst_runs = int(state.get("analyst_runs") or 0)
    limit = settings.max_specialist_runs
    has_research = bool((state.get("research_notes") or "").strip())
    has_analysis = bool((state.get("analysis_notes") or "").strip())
    retry_research = research_runs < limit and (not has_research or "researcher" in feedback)
    retry_analyst = analyst_runs < limit and (not has_analysis or "analyst" in feedback)
    if retry_research or retry_analyst:
        return "supervisor"
    return "synthesizer"


def compile_graph(config: LLMConfig, checkpointer: BaseCheckpointSaver) -> CompiledStateGraph:
    """Compile the orchestrator with Redis (or memory) checkpoints and HITL interrupt."""
    cache: dict[str, BaseChatModel] = {}

    def get_model() -> BaseChatModel:
        if "model" not in cache:
            cache["model"] = LLMFactory.create_client(config).get_llm_model()
        return cache["model"]

    workflow = StateGraph(OrchestratorState)
    workflow.add_node("supervisor", make_supervisor_node(get_model))
    workflow.add_node("hitl_gate", hitl_gate_node)
    workflow.add_node("researcher", make_research_node(get_model))
    workflow.add_node("analyst", make_analyst_node(get_model))
    workflow.add_node("validator", validator_node)
    workflow.add_node("synthesizer", make_synthesizer_node(get_model))

    workflow.add_edge(START, "supervisor")
    workflow.add_conditional_edges(
        "supervisor",
        route_from_supervisor,
        {
            "hitl_gate": "hitl_gate",
            "analyst": "analyst",
            "validator": "validator",
            "synthesizer": "synthesizer",
        },
    )
    workflow.add_edge("hitl_gate", "researcher")
    workflow.add_edge("researcher", "supervisor")
    workflow.add_edge("analyst", "supervisor")
    workflow.add_conditional_edges(
        "validator",
        route_from_validator,
        {"supervisor": "supervisor", "synthesizer": "synthesizer"},
    )
    workflow.add_edge("synthesizer", END)
    return workflow.compile(checkpointer=checkpointer)


def run_config(thread_id: str) -> dict:
    """LangGraph config for one job thread."""
    return {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": settings.recursion_limit,
    }


def final_answer_from_state(state: OrchestratorState | dict) -> str:
    """Extract the synthesizer answer from contributions or last AI message."""
    for item in reversed(state.get("contributions") or []):
        if item.get("kind") == "synthesis" and (item.get("content") or "").strip():
            return item["content"].strip()
    messages = state.get("messages") or []
    for message in reversed(messages):
        content = getattr(message, "content", None)
        if isinstance(content, str) and content.strip():
            return content.strip()
    return ""


def interrupts_from_state(snapshot) -> list[dict]:
    """Collect interrupt payloads from a StateSnapshot."""
    payloads: list[dict] = []
    for task in getattr(snapshot, "tasks", ()) or ():
        for item in getattr(task, "interrupts", ()) or ():
            value = getattr(item, "value", item)
            if isinstance(value, dict):
                payloads.append(value)
            else:
                payloads.append({"value": value})
    return payloads
