"""
TenderSentry Analysis Pipeline — Thin Orchestrator

This module orchestrates the LangGraph agent across FastAPI requests.
It manages session lifecycle, background graph runs, and status polling.

Exports:
    get_graph() — lazy-init and return the compiled graph
    start_analysis(session_id, pdf_paths) — start a background graph run
    get_status(session_id) — poll current status of a session
    submit_decision(session_id, decision) — resume a paused graph

Layer: imports from constants, logging, and components only.
Thread-safe: graph.stream() is thread-safe via SqliteSaver checkpointer.

Import pattern:
    from tendersentry.pipeline.analysis_pipeline import (
        get_graph, start_analysis, get_status, submit_decision
    )
"""

import threading
from langgraph.types import Command

from tendersentry.components.agent import TenderState, build_graph
from tendersentry.constants import (
    STATUS_RUNNING,
    STATUS_HITL_PENDING,
    STATUS_COMPLETE,
    STATUS_ERROR,
    DECISION_FLAG,
    DECISION_DISMISS,
    DECISION_ESCALATE,
)
from tendersentry.logging.logger import logging


# ============================================================================
# Module-Level Graph Instance (Lazy Init)
# ============================================================================

_graph = None


def get_graph():
    """
    Lazy-initialize and return the compiled LangGraph graph.

    The graph is built once and reused across all sessions. Each session
    has its own thread_id in SqliteSaver, enabling concurrent analysis.

    Returns:
        Compiled LangGraph workflow instance.

    Raises:
        Exception: If graph compilation fails.
    """
    global _graph
    if _graph is None:
        logging.info("get_graph: initializing graph (first call)")
        _graph = build_graph()
    return _graph


# ============================================================================
# start_analysis — Launch Background Graph Run
# ============================================================================

def start_analysis(session_id: str, pdf_paths: list[str]) -> None:
    """
    Start a graph run in a background thread.

    The graph executes: extract → compare → investigate → hitl_review (pauses).
    The thread runs until the first interrupt() call (at hitl_review node).
    FastAPI /api/status polls for the current state while the graph runs.

    Args:
        session_id: Unique session identifier.
        pdf_paths: List of absolute paths to PDF files.

    Returns:
        None. The thread runs asynchronously; callers must poll get_status() to
        track progress.

    Raises:
        None. Logs errors and continues; does not raise to caller.
    """
    # Build initial state with all required fields
    initial_state: TenderState = {
        "session_id": session_id,
        "pdf_paths": pdf_paths,
        "documents": [],
        "contradictions": [],
        "findings": [],
        "current_finding_idx": 0,
        "human_decision": None,
        "audit_entries": [],
        "error": None,
    }

    # Thread config: SqliteSaver uses thread_id to isolate sessions
    thread_config = {"configurable": {"thread_id": session_id}}

    def _run():
        """Background worker: stream graph until interrupt or END."""
        try:
            graph = get_graph()
            # stream() runs the graph and yields state after each node;
            # it blocks here until interrupt() is hit or graph ends
            for event in graph.stream(initial_state, thread_config, stream_mode="values"):
                pass  # state updates are persisted by SqliteSaver
            logging.info(f"start_analysis: graph stream completed for session {session_id}")
        except Exception as e:
            logging.error(
                f"start_analysis: graph stream failed for session {session_id}: "
                f"{type(e).__name__}: {str(e)}"
            )

    # Launch thread as daemon so server shutdown does not hang
    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    logging.info(f"start_analysis: launched background thread for session {session_id}")


# ============================================================================
# get_status — Poll Current Session Status
# ============================================================================

def get_status(session_id: str) -> dict:
    """
    Return current status of a session.

    Polls the graph state to determine where the session is in its lifecycle.
    Returns a dict with "status" key and optional metadata.

    Possible return values:
        {"status": "running"} — graph is executing, no interrupt yet
        {"status": "hitl_pending", "finding": {...}} — paused, finding ready for review
        {"status": "complete", "summary": {...}} — all findings reviewed successfully
        {"status": "error", "message": "..."} — graph failed

    Args:
        session_id: Unique session identifier.

    Returns:
        dict: Status dict with "status" key and optional "finding", "summary", or "message".

    Raises:
        None. Returns STATUS_RUNNING if state cannot be retrieved (session not yet started).
    """
    thread_config = {"configurable": {"thread_id": session_id}}
    graph = get_graph()

    try:
        state_snapshot = graph.get_state(thread_config)
    except Exception as e:
        logging.warning(
            f"get_status: failed to get state for session {session_id}: "
            f"{type(e).__name__}. Returning running."
        )
        return {"status": STATUS_RUNNING}

    # No state yet; session not started or still initializing
    if not state_snapshot or not state_snapshot.values:
        return {"status": STATUS_RUNNING}

    state = state_snapshot.values

    # Check for error in state
    if state.get("error"):
        error_msg = state["error"]
        logging.info(f"get_status: error found for session {session_id}: {error_msg}")
        return {"status": STATUS_ERROR, "message": error_msg}

    # Check for interrupt (hitl_review paused for human decision)
    # LangGraph's interrupt() stores pending tasks that we can inspect
    if state_snapshot.tasks:
        for task in state_snapshot.tasks:
            if hasattr(task, "interrupts") and task.interrupts:
                # task.interrupts[0].value is the finding dict passed to interrupt()
                finding_dict = task.interrupts[0].value
                logging.info(
                    f"get_status: hitl_review paused for session {session_id}, "
                    f"finding {finding_dict.get('finding_id')}"
                )
                contradictions = state_snapshot.values.get("contradictions", [])
                return {
                    "status": STATUS_HITL_PENDING,
                    "finding": finding_dict,
                    "finding_count": len(contradictions),
                }

    # Graph reached END — complete regardless of finding/audit counts.
    # Covers: 0 contradictions, all reviewed, or partial findings after worker failure.
    documents = state.get("documents", [])
    graph_done = not state_snapshot.next and not state_snapshot.tasks
    if graph_done and documents:
        contradictions = state.get("contradictions", [])
        findings = state.get("findings", [])
        audit_entries = state.get("audit_entries", [])
        logging.info(
            f"get_status: analysis complete for session {session_id}: "
            f"{len(contradictions)} detected, {len(findings)} findings, "
            f"{len(audit_entries)} decisions"
        )
        return {
            "status": STATUS_COMPLETE,
            "summary": {
                "session_id": session_id,
                "total_detected": len(contradictions),
                "total_findings": len(findings),
                "total_decisions": len(audit_entries),
                "findings": findings,
                "audit_entries": audit_entries,
            }
        }

    # Still running (extract, compare, investigate, or between HITL loops)
    return {"status": STATUS_RUNNING}


# ============================================================================
# submit_decision — Resume Paused Graph
# ============================================================================

def submit_decision(session_id: str, decision: str) -> bool:
    """
    Resume a paused graph with a human decision.

    Called by POST /api/decision route. Sends Command(resume=decision) to
    the paused hitl_review node, which resumes graph execution.
    The decision value is passed to the hitl_review_node's interrupt() and
    stored in state["human_decision"].

    The graph then routes to either investigate (next finding) or END
    based on route_after_hitl().

    Args:
        session_id: Unique session identifier (must be paused at hitl_review).
        decision: Human decision ("flag", "dismiss", or "escalate").

    Returns:
        bool: True on success (thread launched), False on error.

    Raises:
        None. Logs errors and returns False; does not raise to caller.
    """
    # Validate decision value (optional; hitl_review also validates)
    valid_decisions = {DECISION_FLAG, DECISION_DISMISS, DECISION_ESCALATE}
    if decision not in valid_decisions:
        logging.warning(
            f"submit_decision: invalid decision '{decision}' for session {session_id}. "
            f"Valid: {valid_decisions}"
        )
        return False

    thread_config = {"configurable": {"thread_id": session_id}}

    def _resume():
        """Background worker: resume graph and stream until next interrupt or END."""
        try:
            graph = get_graph()
            # Command(resume=decision) sends decision to hitl_review's interrupt()
            for event in graph.stream(
                Command(resume=decision),
                thread_config,
                stream_mode="values"
            ):
                pass  # state updates are persisted by SqliteSaver
            logging.info(
                f"submit_decision: graph stream completed for session {session_id} "
                f"after resuming with decision '{decision}'"
            )
        except Exception as e:
            logging.error(
                f"submit_decision: graph stream failed for session {session_id}: "
                f"{type(e).__name__}: {str(e)}"
            )

    # Launch thread as daemon
    thread = threading.Thread(target=_resume, daemon=True)
    thread.start()
    logging.info(
        f"submit_decision: launched resume thread for session {session_id} "
        f"with decision '{decision}'"
    )
    return True
