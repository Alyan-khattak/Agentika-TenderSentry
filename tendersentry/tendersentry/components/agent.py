"""
TenderSentry LangGraph Agent

The core stateful agent graph that orchestrates contradiction detection and human review.
This module defines the TenderState, all node functions (extract, compare, investigate),
routing logic, and graph compilation.

Architecture:
    extract → compare → investigate ↔ hitl_review → END

- extract: PDFExtractor → ExtractionArtifact → serialize DocumentChunk dicts
- compare: ContradictionDetector → list[RawContradiction] → serialize to dicts
- investigate: For each contradiction, call LLM + jev → Finding → append to findings
- hitl_review: STUB (owned by hitl-agent); will use interrupt() to pause for human decision

State serialization:
    All Pydantic models are converted to dicts via .model_dump() before storing in state
    (LangGraph's SqliteSaver requires JSON-serializable values).
    Models are reconstructed from dicts via Model(**dict) when reading from state.

Layer: imports from constants, entity, utils, exception, logging only.

Import pattern:
    from tendersentry.components.agent import TenderState, build_graph
"""

from typing import TypedDict, Optional
from collections import defaultdict
import sqlite3
from datetime import datetime

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import interrupt
from langgraph.errors import GraphInterrupt

from tendersentry.entity.config_entity import (
    ExtractorConfig, ComparatorConfig
)
from tendersentry.entity.artifact_entity import (
    DocumentChunk, RawContradiction, Finding, FindingExplanation
)
from tendersentry.components.extractor import PDFExtractor
from tendersentry.components.comparators import ContradictionDetector
from tendersentry.utils.utils import get_instructor_client, call_jev
from tendersentry.constants import (
    LLM_MODEL_PRIMARY, LLM_MAX_RETRIES, DB_PATH, ARTIFACTS_DIR,
    DATE_TOLERANCE_DAYS, AMOUNT_TOLERANCE_PCT, REQUIREMENT_KEYWORD_PAIRS,
    DECISION_FLAG, DECISION_DISMISS, DECISION_ESCALATE,
)
from tendersentry.logging.logger import logging


# ============================================================================
# TenderState — The Single Source of Truth
# ============================================================================

class TenderState(TypedDict):
    """
    LangGraph state for the TenderSentry agent.

    All fields are JSON-serializable (dicts, not Pydantic models) to work with SqliteSaver.
    Pydantic models are serialized to dicts at node boundaries.

    Attributes:
        session_id: Unique session identifier for this analysis run.
        pdf_paths: List of absolute paths to PDF files to analyze.
        documents: List of serialized DocumentChunk dicts (from extract node).
        contradictions: List of serialized RawContradiction dicts (from compare node).
        findings: List of serialized Finding dicts (accumulated by investigate node).
        current_finding_idx: 0-indexed pointer to the contradiction being processed.
        human_decision: Decision from HITL review ("flag", "dismiss", "escalate", or None).
        audit_entries: List of audit log entries (decisions, timestamps, etc.).
        error: Error message if a node failed (None if no error).
    """
    session_id: str
    pdf_paths: list[str]
    documents: list[dict]           # serialized DocumentChunk
    contradictions: list[dict]      # serialized RawContradiction
    findings: list[dict]            # serialized Finding
    current_finding_idx: int
    human_decision: Optional[str]
    audit_entries: list[dict]
    error: Optional[str]


# ============================================================================
# Node 1: Extract
# ============================================================================

def extract_node(state: TenderState) -> dict:
    """
    Extract text from PDFs and store as DocumentChunk dicts in state.

    Reads PDF files from state["pdf_paths"], extracts text page by page,
    and returns a list of serialized DocumentChunk objects.

    Flow:
        1. Create ExtractorConfig from constants and state pdf_paths
        2. Instantiate PDFExtractor with config
        3. Call .extract() → ExtractionArtifact
        4. Serialize chunks to dicts via .model_dump()
        5. Return {"documents": [chunk_dicts]}

    Args:
        state: TenderState dict with pdf_paths field populated.

    Returns:
        dict with "documents" key (list of dicts) on success,
        or "error" key (str) on failure.
    """
    logging.info(f"extract_node: starting for session {state['session_id']}")

    try:
        # Create config and extractor
        config = ExtractorConfig(
            pdf_paths=state["pdf_paths"],
            artifacts_dir=ARTIFACTS_DIR,
        )
        extractor = PDFExtractor(config)

        # Extract text from PDFs
        artifact = extractor.extract()

        # Serialize DocumentChunk objects to dicts
        documents_dicts = [chunk.model_dump() for chunk in artifact.chunks]

        logging.info(
            f"extract_node: extracted {len(documents_dicts)} pages from "
            f"{len(state['pdf_paths'])} PDF(s)"
        )
        return {"documents": documents_dicts}

    except Exception as e:
        error_msg = f"extract_node failed: {type(e).__name__}: {str(e)}"
        logging.error(error_msg)
        return {"error": error_msg}


# ============================================================================
# Node 2: Compare
# ============================================================================

def compare_node(state: TenderState) -> dict:
    """
    Run deterministic comparators on extracted chunks and detect contradictions.

    Chunks are grouped by tender_ref (extracted from page 1 of each PDF).
    Contradictions are only detected within groups of PDFs from the same tender.

    Flow:
        1. Deserialize documents from state["documents"] → list[DocumentChunk]
        2. Group DocumentChunk objects by tender_ref (or "__ungrouped__" if None)
        3. For each group with 2+ chunks:
           - Create ComparatorConfig from constants
           - Instantiate ContradictionDetector with config
           - Call .detect(group_chunks) → list[RawContradiction]
        4. Combine contradictions from all groups
        5. Serialize to dicts via .model_dump()
        6. Return {"contradictions": [contradiction_dicts], "current_finding_idx": 0}

    Args:
        state: TenderState dict with "documents" field populated.

    Returns:
        dict with "contradictions" key (list of dicts) on success,
        or "error" key (str) on failure.
    """
    logging.info(f"compare_node: starting for session {state['session_id']}")

    try:
        # Deserialize DocumentChunk dicts back to Pydantic objects
        documents = [DocumentChunk(**doc_dict) for doc_dict in state["documents"]]

        # Group chunks by tender_ref; ungrouped chunks go to "__ungrouped__"
        groups = defaultdict(list)
        for chunk in documents:
            key = chunk.tender_ref or "__ungrouped__"
            groups[key].append(chunk)

        logging.info(f"compare_node: {len(groups)} tender group(s): {list(groups.keys())}")

        # Create config and detector (reused for all groups)
        config = ComparatorConfig(
            date_tolerance_days=DATE_TOLERANCE_DAYS,
            amount_tolerance_pct=AMOUNT_TOLERANCE_PCT,
            requirement_keyword_pairs=REQUIREMENT_KEYWORD_PAIRS,
        )
        detector = ContradictionDetector(config)

        # Detect contradictions within each group separately
        all_contradictions = []
        for group_key, group_chunks in groups.items():
            if len(group_chunks) < 2:
                logging.info(f"compare_node: group '{group_key}' has only {len(group_chunks)} chunk(s), skipping")
                continue

            # Run comparators on this group
            group_contradictions = detector.detect(group_chunks)
            logging.info(
                f"compare_node: group '{group_key}' ({len(group_chunks)} chunks) → "
                f"{len(group_contradictions)} contradiction(s)"
            )
            # Stamp each contradiction with its tender_ref
            ref = group_key if group_key != "__ungrouped__" else None
            for c in group_contradictions:
                d = c.model_dump()
                d["tender_ref"] = ref
                all_contradictions.append(RawContradiction(**d))

        # Serialize RawContradiction objects to dicts
        contradictions_dicts = [c.model_dump() for c in all_contradictions]

        logging.info(
            f"compare_node: detected {len(contradictions_dicts)} total contradiction(s) "
            f"across all groups"
        )
        return {
            "contradictions": contradictions_dicts,
            "current_finding_idx": 0,  # Start at first contradiction
        }

    except Exception as e:
        error_msg = f"compare_node failed: {type(e).__name__}: {str(e)}"
        logging.error(error_msg)
        return {"error": error_msg}


# ============================================================================
# Node 3: Investigate
# ============================================================================

def investigate_node(state: TenderState) -> dict:
    """
    For the current contradiction, get LLM explanation and jev validation.

    Flow:
        1. Get idx = state["current_finding_idx"]
        2. Deserialize contradiction from state["contradictions"][idx]
        3. Build LLM prompt with contradiction context
        4. Call instructor-wrapped Groq client → FindingExplanation
        5. Call call_jev() → JevValidation
        6. Build Finding object combining contradiction + explanation + jev
        7. Serialize Finding to dict and append to findings
        8. Increment current_finding_idx
        9. Return {"findings": findings_dicts, "current_finding_idx": idx+1}

    Args:
        state: TenderState dict with contradictions and current_finding_idx populated.

    Returns:
        dict with "findings" key (list of dicts) on success,
        or "error" key (str) on failure.
    """
    logging.info(f"investigate_node: starting for session {state['session_id']}")

    try:
        # Get the index of the contradiction to investigate
        idx = state["current_finding_idx"]
        total = len(state["contradictions"])

        if idx >= total:
            # No more contradictions to investigate
            logging.info(f"investigate_node: all {total} contradiction(s) processed")
            return {"findings": state["findings"]}

        # Deserialize the current contradiction
        contradiction_dict = state["contradictions"][idx]
        contradiction = RawContradiction(**contradiction_dict)

        logging.info(
            f"investigate_node: processing contradiction {idx + 1}/{total} "
            f"({contradiction.finding_id}: {contradiction.contradiction_type})"
        )

        # Build context string for LLM and jev
        context = (
            f"Document A ({contradiction.doc_a}):\n{contradiction.excerpt_a}\n\n"
            f"Document B ({contradiction.doc_b}):\n{contradiction.excerpt_b}\n\n"
            f"Contradiction Type: {contradiction.contradiction_type}"
        )

        # ============ LLM Explanation ============
        # Build LLM prompt
        llm_prompt = (
            f"You are a procurement compliance expert. Analyze this contradiction "
            f"found in tender documents.\n\n"
            f"Document A ({contradiction.doc_a}): {contradiction.excerpt_a}\n"
            f"Document B ({contradiction.doc_b}): {contradiction.excerpt_b}\n"
            f"Type: {contradiction.contradiction_type}\n\n"
            f"Provide:\n"
            f"1. A clear plain-language explanation of the contradiction and why it matters to bidders\n"
            f"2. A specific question the procurement officer should raise with the issuing authority\n"
            f"3. A severity level (HIGH, MEDIUM, or LOW)\n\n"
            f"Be concise and precise."
        )

        # Call instructor-wrapped Groq client for structured output
        try:
            client = get_instructor_client()
            explanation_obj = client.chat.completions.create(
                model=LLM_MODEL_PRIMARY,
                response_model=FindingExplanation,
                messages=[{"role": "user", "content": llm_prompt}],
                max_retries=LLM_MAX_RETRIES,
            )
            logging.info(f"investigate_node: LLM explanation obtained for {contradiction.finding_id}")

        except Exception as e:
            # LLM failed; use default values for explanation
            logging.error(
                f"investigate_node: LLM call failed for {contradiction.finding_id}: {type(e).__name__}"
            )
            explanation_obj = FindingExplanation(
                explanation="Unable to generate explanation due to LLM error.",
                suggested_question="Please review the contradiction manually.",
                severity=contradiction.severity,
            )

        # ============ jev Validation ============
        # Call jev to validate the contradiction
        jev_result = call_jev(context, contradiction.contradiction_type)

        # ============ Build Finding ============
        # Combine contradiction, explanation, and jev into a Finding
        finding = Finding(
            finding_id=contradiction.finding_id,
            contradiction_type=contradiction.contradiction_type,
            doc_a=contradiction.doc_a,
            excerpt_a=contradiction.excerpt_a,
            doc_b=contradiction.doc_b,
            excerpt_b=contradiction.excerpt_b,
            explanation=explanation_obj.explanation,
            suggested_question=explanation_obj.suggested_question,
            severity=explanation_obj.severity,  # Use LLM-adjusted severity
            jev_genuine=jev_result.jev_genuine,
            jev_severity=jev_result.jev_severity,
            jev_category=jev_result.jev_category,
            jev_available=jev_result.jev_available,
            tender_ref=contradiction.tender_ref,
        )

        # Serialize Finding to dict and append to findings
        findings_dicts = state["findings"] + [finding.model_dump()]

        logging.info(
            f"investigate_node: completed {contradiction.finding_id} "
            f"(jev_genuine={jev_result.jev_genuine:.2f})"
        )

        return {
            "findings": findings_dicts,
            "current_finding_idx": idx + 1,
        }

    except Exception as e:
        error_msg = f"investigate_node failed: {type(e).__name__}: {str(e)}"
        logging.error(error_msg)
        return {"error": error_msg}


# ============================================================================
# Routing Functions
# ============================================================================

def route_after_compare(state: TenderState) -> str:
    """
    Route after compare node: if contradictions found, go to investigate; else END.

    Args:
        state: TenderState dict with contradictions field.

    Returns:
        "investigate" if contradictions exist, END otherwise.
    """
    if state.get("contradictions"):
        logging.info(f"route_after_compare: {len(state['contradictions'])} contradiction(s) found, going to investigate")
        return "investigate"
    else:
        logging.info("route_after_compare: no contradictions found, ending graph")
        return END


def route_after_hitl(state: TenderState) -> str:
    """
    Route after hitl_review node: if more contradictions to investigate, loop; else END.

    Args:
        state: TenderState dict with current_finding_idx and contradictions.

    Returns:
        "investigate" if more contradictions to process, END otherwise.
    """
    idx = state.get("current_finding_idx", 0)
    total = len(state.get("contradictions", []))

    if idx < total:
        logging.info(f"route_after_hitl: {idx}/{total} processed, looping to investigate")
        return "investigate"
    else:
        logging.info(f"route_after_hitl: all {total} contradiction(s) processed, ending graph")
        return END


# ============================================================================
# Node 4: HITL Review (STUB)
# ============================================================================

def hitl_review_node(state: TenderState) -> dict:
    """
    Pause graph for human review of the current finding.

    Uses LangGraph interrupt() to pause execution. The FastAPI route POST /api/decision
    resumes the graph with Command(resume=decision), passing the human's choice
    (flag / dismiss / escalate).

    Flow:
        1. Get the most recently investigated finding (findings[current_finding_idx - 1])
        2. Call interrupt(finding_dict) — graph pauses here
        3. On resume: human_decision is passed back via Command(resume=decision)
        4. Validate decision is one of: flag, dismiss, escalate
        5. Build audit entry dict and append to audit_entries
        6. Return state updates

    Args:
        state: TenderState dict with findings and current_finding_idx populated.

    Returns:
        dict with "human_decision" and "audit_entries" keys on success,
        or "error" key (str) on failure.
    """
    logging.info(f"hitl_review_node: starting for session {state['session_id']}")

    try:
        # Get the finding that was just investigated
        findings = state.get("findings", [])
        if not findings:
            logging.warning("hitl_review_node: no findings in state, skipping")
            return {}

        # The most recent finding is at current_finding_idx - 1
        # (investigate_node increments current_finding_idx after building the finding)
        finding_idx = state["current_finding_idx"] - 1
        if finding_idx < 0 or finding_idx >= len(findings):
            logging.warning(
                f"hitl_review_node: invalid finding_idx {finding_idx}, "
                f"findings count {len(findings)}"
            )
            return {}

        finding_dict = findings[finding_idx]

        # Pause graph — FastAPI GET /api/status will return this finding to the frontend
        # The value passed to interrupt() is available via GET /api/status/{session_id}
        # When human clicks a button, POST /api/decision calls Command(resume=decision)
        decision = interrupt(finding_dict)

        # decision is the string passed to Command(resume=decision) by POST /api/decision
        # Validate it
        valid_decisions = {DECISION_FLAG, DECISION_DISMISS, DECISION_ESCALATE}
        if decision not in valid_decisions:
            logging.warning(
                f"hitl_review_node: invalid decision '{decision}', defaulting to dismiss"
            )
            decision = DECISION_DISMISS

        # Build audit entry with all required fields from the finding
        audit_entry = {
            "finding_id": finding_dict["finding_id"],
            "contradiction_type": finding_dict["contradiction_type"],
            "severity": finding_dict["severity"],
            "doc_a": finding_dict["doc_a"],
            "excerpt_a": finding_dict["excerpt_a"],
            "doc_b": finding_dict["doc_b"],
            "excerpt_b": finding_dict["excerpt_b"],
            "explanation": finding_dict["explanation"],
            "jev_genuine": finding_dict["jev_genuine"],
            "jev_severity": finding_dict["jev_severity"],
            "jev_category": finding_dict["jev_category"],
            "tender_ref": finding_dict.get("tender_ref"),
            "human_decision": decision,
            "human_note": "",  # main.py /api/decision route will set this via log_decision()
            "decided_at": datetime.utcnow().isoformat(),
        }

        logging.info(
            f"hitl_review_node: decision '{decision}' recorded for {finding_dict['finding_id']}"
        )

        return {
            "human_decision": decision,
            "audit_entries": state.get("audit_entries", []) + [audit_entry],
        }

    except GraphInterrupt:
        raise  # LangGraph interrupt — must propagate, not be caught as an error
    except Exception as e:
        error_msg = f"hitl_review_node failed: {type(e).__name__}: {str(e)}"
        logging.error(error_msg)
        return {"error": error_msg}


# ============================================================================
# Graph Builder
# ============================================================================

def build_graph(db_path: str = None):
    """
    Build and compile the TenderSentry LangGraph agent graph.

    The graph orchestrates contradiction detection and human review:
        extract → compare → investigate ↔ hitl_review → END

    Checkpointing:
        Uses SqliteSaver to persist graph state to SQLite, enabling recovery
        across server restarts. The hitl_review node uses interrupt() to pause
        for human decision; Command(resume=decision) resumes execution.

    Args:
        db_path: Path to SQLite database file (default: DB_PATH from constants).
                 If the file does not exist, SqliteSaver creates it.

    Returns:
        Compiled LangGraph workflow instance (callable with graph.invoke() or graph.stream()).

    Raises:
        Exception: If SqliteSaver fails to connect to the database.
    """
    db_path = db_path or DB_PATH
    logging.info(f"build_graph: building agent graph with checkpointer at {db_path}")

    # Create the state graph
    workflow = StateGraph(TenderState)

    # Add nodes
    workflow.add_node("extract", extract_node)
    workflow.add_node("compare", compare_node)
    workflow.add_node("investigate", investigate_node)
    workflow.add_node("hitl_review", hitl_review_node)

    # Set entry point
    workflow.set_entry_point("extract")

    # Add edges: extract → compare
    workflow.add_edge("extract", "compare")

    # Conditional edge: compare → (investigate or END)
    workflow.add_conditional_edges(
        "compare",
        route_after_compare,
        {"investigate": "investigate", END: END}
    )

    # Edge: investigate → hitl_review
    workflow.add_edge("investigate", "hitl_review")

    # Conditional edge: hitl_review → (investigate or END)
    # This loop allows processing multiple contradictions
    workflow.add_conditional_edges(
        "hitl_review",
        route_after_hitl,
        {"investigate": "investigate", END: END}
    )

    # Set up checkpointer with SqliteSaver
    # IMP: SqliteSaver requires a direct sqlite3 connection, not from_conn_string
    try:
        conn = sqlite3.connect(db_path, check_same_thread=False)
        memory = SqliteSaver(conn)
        logging.info(f"build_graph: SqliteSaver initialized with {db_path}")
    except Exception as e:
        logging.error(f"build_graph: SqliteSaver failed: {type(e).__name__}: {str(e)}")
        raise

    # Compile the graph
    try:
        graph = workflow.compile(checkpointer=memory)
        logging.info("build_graph: graph compiled successfully")
        return graph
    except Exception as e:
        logging.error(f"build_graph: graph compilation failed: {type(e).__name__}: {str(e)}")
        raise
