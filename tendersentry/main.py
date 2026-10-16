"""
TenderSentry FastAPI Application

Main entry point for the TenderSentry AI contradiction detector. Provides 4 REST API
endpoints for file upload, status polling, human decision submission, and audit log
retrieval. Coordinates with the LangGraph analysis pipeline and SQLite audit database.

The FastAPI app is initialized at startup with database tables and artifact directory.
All routes validate input at the boundary, call pipeline/database functions, and return
typed Pydantic responses or JSONResponse.

Routes:
  POST   /api/analyse          - Accept 2-5 PDF files, validate, save, start analysis
  GET    /api/status/{id}      - Poll for current analysis status (running/hitl_pending/complete/error)
  POST   /api/decision         - Submit human decision (flag/dismiss/escalate) on a finding
  GET    /api/audit-log        - Return all audit log entries

Mount:
  /                            - Serve static/index.html and assets (HTML, CSS, JS)

Environment:
  - Loads .env at startup for secrets (API keys via python-dotenv)
  - ARTIFACTS_DIR: directory for uploaded PDFs and logs
  - DB_PATH: SQLite database location for audit_log and sessions

Implementation notes:
  - File uploads saved to {ARTIFACTS_DIR}/{session_id}/ before analysis starts
  - session_id generated as uuid4().hex[:8].upper() — 8-char uppercase string
  - Each route logs at start and end (INFO level)
  - Error handling: HTTPException 400 for validation, 500 for server errors
  - Static files mounted last to avoid catching API routes

"""

import os
import shutil
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, UploadFile, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

# Import from tendersentry modules (layer order: constants → logging → database → pipeline)
from tendersentry.constants import (
    MAX_FILE_SIZE_BYTES,
    ALLOWED_EXTENSIONS,
    ARTIFACTS_DIR,
    STATIC_DIR,
    STATUS_COMPLETE,
    STATUS_ERROR,
    STATUS_HITL_PENDING,
    DECISION_FLAG,
    DECISION_DISMISS,
    DECISION_ESCALATE,
)
from tendersentry.logging.logger import logging
from tendersentry.exception.exception import TenderSentryException
from database import init_db, log_session, log_decision, complete_session, get_audit_log, get_session

# Import pipeline functions (lazy import to allow for gradual development)
try:
    from tendersentry.pipeline.analysis_pipeline import (
        start_analysis,
        get_status,
        submit_decision,
    )
except ImportError:
    # Graceful degradation if pipeline not yet implemented
    logging.warning("analysis_pipeline module not yet available — routes will fail gracefully")
    start_analysis = None
    get_status = None
    submit_decision = None


# ============================================================================
# FastAPI Application Setup
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        logging.info("TenderSentry startup: initializing database and artifact directories")
        init_db()
        os.makedirs(ARTIFACTS_DIR, exist_ok=True)
        logging.info("Startup complete: database initialized, artifact directory ready")
    except Exception as e:
        logging.error(f"Startup failed: {str(e)}")
        raise TenderSentryException(f"Startup failed: {str(e)}", __import__("sys"))
    yield


app = FastAPI(
    title="TenderSentry",
    description="AI contradiction detector for public tender PDFs",
    version="0.1.0",
    lifespan=lifespan,
)


# ============================================================================
# Request/Response Models
# ============================================================================

class DecisionRequest(BaseModel):
    """
    Human decision submission for a finding.

    Attributes:
        session_id: Session identifier (e.g., 'A3F7C1B2')
        finding_id: Finding identifier (e.g., 'F-001')
        decision: Human decision — one of 'flag', 'dismiss', 'escalate'
        note: Optional reviewer note (default: empty string)
    """

    session_id: str = Field(..., description="Session ID")
    finding_id: str = Field(..., description="Finding ID")
    decision: str = Field(..., description="Decision: flag, dismiss, or escalate")
    note: str = Field(default="", description="Optional reviewer note")


class AnalyseResponse(BaseModel):
    """Response for POST /api/analyse."""

    session_id: str = Field(..., description="Unique session identifier")


class DecisionResponse(BaseModel):
    """Response for POST /api/decision."""

    ok: bool = Field(default=True, description="Success indicator")


# ============================================================================
# Route: POST /api/analyse
# ============================================================================

@app.post("/api/analyse", response_model=AnalyseResponse)
async def analyse(files: list[UploadFile] = File(...), mode: str = Form(default="standard")):
    """
    Accept 2-5 PDF files, validate, save to disk, and start analysis.

    Validation:
    - Each file must be a .pdf (case-insensitive extension check)
    - Each file must be ≤ MAX_FILE_SIZE_BYTES (10 MB)
    - At least 2 files required (implicit in task spec: "2-5 PDFs")

    On success:
    - Generates session_id = uuid4().hex[:8].upper()
    - Saves each file to {ARTIFACTS_DIR}/{session_id}/{filename}
    - Calls log_session(session_id, [filenames], 0, 0) — counts set to 0 initially
    - Calls start_analysis(session_id, [saved_paths]) — begins LangGraph agent
    - Returns session_id to frontend for polling

    Errors:
    - 400 Bad Request: invalid file type or exceeds size limit
    - 400 Bad Request: fewer than 2 files (per task spec)

    Args:
        files: List of uploaded PDF files (FastAPI automatic multipart parsing)

    Returns:
        AnalyseResponse with session_id (e.g., "A3F7C1B2")
    """
    logging.info(f"POST /api/analyse: received {len(files)} files")

    try:
        # ────────────────────────────────────────────────────────────────
        # Validation: file count
        # ────────────────────────────────────────────────────────────────
        if len(files) < 2:
            logging.warning(f"POST /api/analyse: rejecting {len(files)} files (minimum 2 required)")
            raise HTTPException(
                status_code=400,
                detail="At least 2 PDF files are required.",
            )

        # ────────────────────────────────────────────────────────────────
        # Validation: file type and size
        # ────────────────────────────────────────────────────────────────
        for file in files:
            # Check extension
            ext = os.path.splitext(file.filename)[1].lower()
            if ext not in ALLOWED_EXTENSIONS:
                logging.warning(f"POST /api/analyse: rejecting {file.filename} — invalid extension {ext}")
                raise HTTPException(
                    status_code=400,
                    detail=f"File '{file.filename}' is not a PDF.",
                )

            # Check size
            content = await file.read()
            if len(content) > MAX_FILE_SIZE_BYTES:
                logging.warning(f"POST /api/analyse: rejecting {file.filename} — size {len(content)} exceeds limit {MAX_FILE_SIZE_BYTES}")
                raise HTTPException(
                    status_code=400,
                    detail=f"File '{file.filename}' exceeds {MAX_FILE_SIZE_BYTES // (1024*1024)} MB limit.",
                )

            # Reset file pointer for saving
            await file.seek(0)

        # ────────────────────────────────────────────────────────────────
        # Generate session_id and create session directory
        # ────────────────────────────────────────────────────────────────
        session_id = uuid.uuid4().hex[:8].upper()
        session_dir = os.path.join(ARTIFACTS_DIR, session_id)
        os.makedirs(session_dir, exist_ok=True)
        logging.info(f"POST /api/analyse: created session {session_id}")

        # ────────────────────────────────────────────────────────────────
        # Save files to session directory
        # ────────────────────────────────────────────────────────────────
        saved_paths = []
        filenames = []

        for file in files:
            file_path = os.path.join(session_dir, os.path.basename(file.filename))
            filenames.append(file.filename)

            # Write uploaded file to disk
            with open(file_path, "wb") as f:
                content = await file.read()
                f.write(content)

            saved_paths.append(file_path)
            logging.info(f"POST /api/analyse: saved {file.filename} to {file_path}")

        # ────────────────────────────────────────────────────────────────
        # Log session in database (counts = 0 initially)
        # ────────────────────────────────────────────────────────────────
        log_session(
            session_id=session_id,
            source_files=filenames,
            total_detected=0,
            total_validated=0,
        )
        logging.info(f"POST /api/analyse: logged session {session_id} with {len(filenames)} files")

        # ────────────────────────────────────────────────────────────────
        # Start analysis pipeline
        # ────────────────────────────────────────────────────────────────
        if start_analysis is None:
            raise HTTPException(
                status_code=500,
                detail="Analysis pipeline not yet initialized. Check server logs.",
            )

        start_analysis(session_id=session_id, pdf_paths=saved_paths, mode=mode)
        logging.info(f"POST /api/analyse: analysis started for session {session_id}")

        return AnalyseResponse(session_id=session_id)

    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"POST /api/analyse: unhandled error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"File upload failed: {str(e)}")


# ============================================================================
# Route: GET /api/status/{session_id}
# ============================================================================

@app.get("/api/status/{session_id}")
async def status(session_id: str):
    """
    Poll for current analysis status.

    Returns the current state of the analysis for a given session. The response
    varies based on status:
    - "running": analysis in progress (extract → compare → investigate)
    - "hitl_pending": paused at HITL review, waiting for human decision
    - "complete": analysis finished, all findings reviewed
    - "error": analysis failed, check message for details

    When status is "hitl_pending", the response includes a "finding" dict with
    the current finding (contradiction_type, severity, doc_a, excerpt_a, etc.).

    When status is "complete", the response includes a "summary" dict with
    total counts (detected, validated, flagged, dismissed, escalated).

    Side effect: If status is "complete", this route calls complete_session()
    to set the completed_at timestamp in the database.

    Args:
        session_id: Session identifier (e.g., 'A3F7C1B2')

    Returns:
        JSON response with status and optional finding/summary

    Errors:
        500: get_status() call failed or pipeline not initialized
    """
    logging.info(f"GET /api/status/{session_id}: polling status")

    try:
        if get_status is None:
            raise HTTPException(
                status_code=500,
                detail="Analysis pipeline not yet initialized.",
            )

        # Call pipeline to get current status
        current_status = get_status(session_id=session_id)

        # Mark session complete once — skip if already stamped
        if current_status.get("status") == STATUS_COMPLETE:
            session = get_session(session_id=session_id)
            if session and not session.get("completed_at"):
                logging.info(f"GET /api/status/{session_id}: marking session complete")
                complete_session(session_id=session_id)

        logging.info(f"GET /api/status/{session_id}: status={current_status.get('status')}")
        return current_status

    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"GET /api/status/{session_id}: unhandled error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Status check failed: {str(e)}")


# ============================================================================
# Route: POST /api/decision
# ============================================================================

@app.post("/api/decision", response_model=DecisionResponse)
async def decision(req: DecisionRequest):
    """
    Submit a human decision on a finding.

    The human has reviewed a finding and clicked one of three buttons:
    - "flag": contradiction is genuine and material
    - "dismiss": contradiction is false or immaterial
    - "escalate": requires legal or procurement review

    This route:
    1. Validates that decision is one of {flag, dismiss, escalate}
    2. Retrieves the current analysis status to locate the finding data
    3. Extracts finding details (contradiction_type, severity, excerpts, etc.)
    4. Calls log_decision() to append to the audit_log table
    5. Calls submit_decision() to resume the paused LangGraph agent

    Args:
        req: DecisionRequest with session_id, finding_id, decision, note

    Returns:
        DecisionResponse with ok=True on success

    Errors:
        400: decision not one of {flag, dismiss, escalate}
        500: status retrieval or decision submission failed
    """
    logging.info(f"POST /api/decision: session={req.session_id}, finding={req.finding_id}, decision={req.decision}")

    try:
        # ────────────────────────────────────────────────────────────────
        # Validation: decision value
        # ────────────────────────────────────────────────────────────────
        valid_decisions = {DECISION_FLAG, DECISION_DISMISS, DECISION_ESCALATE}
        if req.decision not in valid_decisions:
            logging.warning(f"POST /api/decision: rejecting invalid decision '{req.decision}'")
            raise HTTPException(
                status_code=400,
                detail=f"Decision must be one of {valid_decisions}.",
            )

        # ────────────────────────────────────────────────────────────────
        # Retrieve current status to find the finding data
        # ────────────────────────────────────────────────────────────────
        if get_status is None:
            raise HTTPException(
                status_code=500,
                detail="Analysis pipeline not yet initialized.",
            )

        current_status = get_status(session_id=req.session_id)

        # Check if analysis is in HITL review state
        if current_status.get("status") != STATUS_HITL_PENDING:
            logging.warning(
                f"POST /api/decision: session {req.session_id} not in hitl_pending state; "
                f"current status = {current_status.get('status')}"
            )
            raise HTTPException(
                status_code=400,
                detail="No pending finding to decide on. Analysis may have completed.",
            )

        # Extract finding from status response
        finding = current_status.get("finding")
        if not finding:
            logging.error(f"POST /api/decision: finding not in status response for {req.session_id}")
            raise HTTPException(
                status_code=500,
                detail="Finding data missing from status. Check server logs.",
            )

        # ────────────────────────────────────────────────────────────────
        # Log decision to audit_log
        # ────────────────────────────────────────────────────────────────
        log_decision(
            session_id=req.session_id,
            finding_id=req.finding_id,
            contradiction_type=finding.get("contradiction_type", "unknown"),
            severity=finding.get("severity", "MEDIUM"),
            doc_a=finding.get("doc_a", ""),
            excerpt_a=finding.get("excerpt_a", ""),
            doc_b=finding.get("doc_b", ""),
            excerpt_b=finding.get("excerpt_b", ""),
            explanation=finding.get("explanation", ""),
            jev_genuine=finding.get("jev_genuine", 0.0),
            jev_severity=finding.get("jev_severity", 0.0),
            jev_category=finding.get("jev_category", "unknown"),
            human_decision=req.decision,
            human_note=req.note,
            tender_ref=finding.get("tender_ref", ""),
        )
        logging.info(f"POST /api/decision: logged decision for finding {req.finding_id}")

        # ────────────────────────────────────────────────────────────────
        # Resume paused LangGraph agent
        # ────────────────────────────────────────────────────────────────
        if submit_decision is None:
            raise HTTPException(
                status_code=500,
                detail="Analysis pipeline not yet initialized.",
            )

        submit_decision(session_id=req.session_id, decision=req.decision)
        logging.info(f"POST /api/decision: resumed analysis for session {req.session_id}")

        return DecisionResponse(ok=True)

    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"POST /api/decision: unhandled error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Decision submission failed: {str(e)}")


# ============================================================================
# Route: GET /api/audit-log
# ============================================================================

@app.get("/api/audit-log")
async def audit_log():
    """
    Return all audit log entries.

    Retrieves all human decisions recorded in the audit_log table, ordered
    by most recent first (id DESC). The audit log is append-only: no decisions
    can be deleted or modified.

    This route is used by the frontend Summary screen to display the full
    history of findings and decisions for all sessions.

    Returns:
        JSON array of audit log rows. Each row includes:
        - id, session_id, finding_id, contradiction_type, severity
        - doc_a, excerpt_a, doc_b, excerpt_b, explanation
        - jev_genuine, jev_severity, jev_category
        - human_decision, human_note, decided_at

    Returns:
        Empty array if no decisions have been logged yet.
    """
    logging.info("GET /api/audit-log: fetching audit log")

    try:
        rows = get_audit_log()
        logging.info(f"GET /api/audit-log: returning {len(rows)} entries")
        return rows

    except Exception as e:
        logging.error(f"GET /api/audit-log: unhandled error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Audit log fetch failed: {str(e)}")


# ============================================================================
# Static File Mount
# ============================================================================

# Mount static files LAST, after all API routes are registered.
# FastAPI router matches @app.get/@app.post decorators first,
# then falls through to mounted apps. Mounting last ensures routes take priority.
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")

logging.info("FastAPI app initialized with 4 API routes + static mount")
