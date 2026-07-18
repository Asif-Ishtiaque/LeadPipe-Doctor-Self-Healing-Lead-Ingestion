"""LangGraph state machine implementing the self-healing loop:

    run_pipeline -> (success) -> END
                 -> (error, retries left) -> heal -> run_pipeline (retry)
                 -> (error, retries exhausted, or heal itself failed) -> human_review -> END

This is the "MOST IMPORTANT FEATURE" of the project: when the cleaning
engine raises on a batch, the graph captures the traceback, asks the local
LLM to patch app/cleaning/transforms.py, and retries the whole pipeline --
up to max_self_heal_retries times -- before giving up and routing the batch
to human review.
"""

from typing import Any, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from app.agent import human_review
from app.agent.healer import ErrorInfo, NotHealable, PatchRejected, capture_error, heal
from app.agent.pipeline import PipelineResult, run_pipeline
from app.mapping.llm_client import OllamaUnavailable
from app.schema.canonical import LeadSource
from app.utils.config import settings


class AgentState(TypedDict):
    source: LeadSource
    raw_data: Any
    retries: int
    max_retries: int
    result: Optional[PipelineResult]
    last_exception: Optional[BaseException]
    last_error: Optional[ErrorInfo]
    heal_error: Optional[str]
    healing_events: list[dict]
    status: str


def _run_pipeline_node(state: AgentState) -> dict:
    try:
        result = run_pipeline(state["source"], state["raw_data"])
        return {"result": result, "last_exception": None, "status": "success"}
    except Exception as exc:  # noqa: BLE001 -- deliberately broad: any pipeline bug triggers healing
        return {"last_exception": exc, "last_error": capture_error(exc), "status": "error"}


def _heal_node(state: AgentState) -> dict:
    try:
        error, _new_source = heal(state["last_exception"])
        event = {
            "attempt": state["retries"] + 1,
            "exception_type": error.exception_type,
            "message": error.message,
        }
        return {
            "retries": state["retries"] + 1,
            "healing_events": [*state["healing_events"], event],
            "status": "healed",
        }
    except (OllamaUnavailable, PatchRejected, NotHealable) as heal_exc:
        return {"status": "heal_failed", "heal_error": str(heal_exc)}


def _human_review_node(state: AgentState) -> dict:
    reason = state.get("heal_error") or "self-healing retries exhausted"
    error = state.get("last_error")
    human_review.enqueue(
        source=state["source"].value,
        raw_data=state["raw_data"],
        reason=reason,
        error_message=error.message if error else "unknown error",
        retries_used=state["retries"],
    )
    return {"status": "human_review"}


def _route_after_run(state: AgentState) -> str:
    if state["status"] == "success":
        return END
    if state["retries"] < state["max_retries"]:
        return "heal"
    return "human_review"


def _route_after_heal(state: AgentState) -> str:
    return "run_pipeline" if state["status"] == "healed" else "human_review"


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("run_pipeline", _run_pipeline_node)
    graph.add_node("heal", _heal_node)
    graph.add_node("human_review", _human_review_node)

    graph.add_edge(START, "run_pipeline")
    graph.add_conditional_edges("run_pipeline", _route_after_run, {END: END, "heal": "heal", "human_review": "human_review"})
    graph.add_conditional_edges("heal", _route_after_heal, {"run_pipeline": "run_pipeline", "human_review": "human_review"})
    graph.add_edge("human_review", END)

    return graph.compile()


_compiled_graph = None


def get_graph():
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_graph()
    return _compiled_graph


def run_self_healing(source: LeadSource, raw_data: Any) -> AgentState:
    initial_state: AgentState = {
        "source": source,
        "raw_data": raw_data,
        "retries": 0,
        "max_retries": settings.max_self_heal_retries,
        "result": None,
        "last_exception": None,
        "last_error": None,
        "heal_error": None,
        "healing_events": [],
        "status": "running",
    }
    return get_graph().invoke(initial_state)
