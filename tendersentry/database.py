"""
Database module for TenderSentry.

Manages SQLite audit log and sessions table. Provides six functions:
- init_db(): create both tables (called at startup)
- log_session(): append a new analysis session
- complete_session(): mark a session completed (ONE UPDATE allowed)
- log_decision(): append a human decision to audit_log (append-only)
- get_audit_log(): fetch all decisions (read-only)
- get_session(): fetch one session by ID (read-only)

All SQL uses parameterized queries. audit_log is append-only (no DELETE/UPDATE).
Each function opens and closes its connection within its scope.
"""

import json
import sqlite3
from datetime import datetime
from tendersentry.constants import DB_PATH


def init_db(db_path: str = None) -> None:
    """
    Create sessions and audit_log tables if they do not exist.
    Called once at FastAPI startup.

    Args:
        db_path: path to SQLite file. Defaults to DB_PATH from constants.
    """
    if db_path is None:
        db_path = DB_PATH

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Create sessions table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_id   TEXT PRIMARY KEY,
            source_files TEXT NOT NULL,
            total_detected  INTEGER NOT NULL DEFAULT 0,
            total_validated INTEGER NOT NULL DEFAULT 0,
            created_at   TEXT NOT NULL,
            completed_at TEXT
        )
    """)

    # Create audit_log table (append-only)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id         TEXT    NOT NULL REFERENCES sessions(session_id),
            finding_id         TEXT    NOT NULL,
            contradiction_type TEXT    NOT NULL,
            severity           TEXT    NOT NULL,
            doc_a              TEXT    NOT NULL,
            excerpt_a          TEXT    NOT NULL,
            doc_b              TEXT    NOT NULL,
            excerpt_b          TEXT    NOT NULL,
            explanation        TEXT    NOT NULL,
            jev_genuine        REAL    NOT NULL DEFAULT 0.0,
            jev_severity       REAL    NOT NULL DEFAULT 0.0,
            jev_category       TEXT    NOT NULL DEFAULT 'unknown',
            human_decision     TEXT    NOT NULL,
            human_note         TEXT    DEFAULT '',
            decided_at         TEXT    NOT NULL
        )
    """)
    # Add tender_ref column to existing databases (safe: no-op if already present)
    try:
        cursor.execute("ALTER TABLE audit_log ADD COLUMN tender_ref TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass

    conn.commit()
    conn.close()


def log_session(
    session_id: str,
    source_files: list,
    total_detected: int,
    total_validated: int,
    db_path: str = None,
) -> None:
    """
    Insert a new analysis session into sessions table.

    Args:
        session_id: unique identifier for this analysis (e.g., 'A3F7C1B2')
        source_files: list of PDF filenames (e.g., ['main.pdf', 'schedule.pdf'])
        total_detected: count of raw contradictions found
        total_validated: count that passed jev genuine threshold
        db_path: path to SQLite file. Defaults to DB_PATH from constants.
    """
    if db_path is None:
        db_path = DB_PATH

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # JSON-encode the list of filenames
    source_files_json = json.dumps(source_files)
    created_at = datetime.utcnow().isoformat()

    cursor.execute(
        """
        INSERT INTO sessions (session_id, source_files, total_detected, total_validated, created_at, completed_at)
        VALUES (?, ?, ?, ?, ?, NULL)
        """,
        (session_id, source_files_json, total_detected, total_validated, created_at),
    )

    conn.commit()
    conn.close()


def complete_session(session_id: str, db_path: str = None) -> None:
    """
    Mark a session as completed by setting completed_at timestamp.
    This is the ONE UPDATE allowed on the sessions table.

    Args:
        session_id: the session to complete
        db_path: path to SQLite file. Defaults to DB_PATH from constants.
    """
    if db_path is None:
        db_path = DB_PATH

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    completed_at = datetime.utcnow().isoformat()

    cursor.execute(
        "UPDATE sessions SET completed_at = ? WHERE session_id = ?",
        (completed_at, session_id),
    )

    conn.commit()
    conn.close()


def log_decision(
    session_id: str,
    finding_id: str,
    contradiction_type: str,
    severity: str,
    doc_a: str,
    excerpt_a: str,
    doc_b: str,
    excerpt_b: str,
    explanation: str,
    jev_genuine: float,
    jev_severity: float,
    jev_category: str,
    human_decision: str,
    human_note: str,
    tender_ref: str = "",
    db_path: str = None,
) -> None:
    """
    Append a human decision to the audit_log table (append-only).
    Called by hitl_review node after a human clicks Flag / Dismiss / Escalate.

    Args:
        session_id: session this decision belongs to
        finding_id: unique ID of the finding (e.g., 'F-001')
        contradiction_type: 'deadline' / 'requirement' / 'amount' / 'missing'
        severity: 'HIGH' / 'MEDIUM' / 'LOW'
        doc_a: filename of first document
        excerpt_a: conflicting text from doc_a
        doc_b: filename of second document
        excerpt_b: conflicting text from doc_b
        explanation: plain-language explanation from LLM
        jev_genuine: jev noul score (0.0–1.0)
        jev_severity: jev severity score (0.0–1.0)
        jev_category: jev choice answer
        human_decision: 'flag' / 'dismiss' / 'escalate'
        human_note: optional reviewer note
        db_path: path to SQLite file. Defaults to DB_PATH from constants.
    """
    if db_path is None:
        db_path = DB_PATH

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    decided_at = datetime.utcnow().isoformat()

    cursor.execute(
        """
        INSERT INTO audit_log
        (session_id, finding_id, contradiction_type, severity, doc_a, excerpt_a,
         doc_b, excerpt_b, explanation, jev_genuine, jev_severity, jev_category,
         human_decision, human_note, decided_at, tender_ref)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session_id,
            finding_id,
            contradiction_type,
            severity,
            doc_a,
            excerpt_a,
            doc_b,
            excerpt_b,
            explanation,
            jev_genuine,
            jev_severity,
            jev_category,
            human_decision,
            human_note,
            decided_at,
            tender_ref or "",
        ),
    )

    conn.commit()
    conn.close()


def get_audit_log(db_path: str = None) -> list:
    """
    Fetch all rows from audit_log, ordered by id DESC (newest first).
    Returns empty list if no rows exist.

    Args:
        db_path: path to SQLite file. Defaults to DB_PATH from constants.

    Returns:
        List of dicts, one per decision.
    """
    if db_path is None:
        db_path = DB_PATH

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM audit_log ORDER BY id DESC")
    rows = cursor.fetchall()

    # Build list of dicts using cursor.description to map column names
    columns = [desc[0] for desc in cursor.description]
    result = [dict(zip(columns, row)) for row in rows]

    conn.close()

    return result


def get_session(session_id: str, db_path: str = None) -> dict:
    """
    Fetch one session by ID.

    Args:
        session_id: the session to look up
        db_path: path to SQLite file. Defaults to DB_PATH from constants.

    Returns:
        Dict with session data (session_id, source_files, total_detected, total_validated, created_at, completed_at),
        or None if not found.
    """
    if db_path is None:
        db_path = DB_PATH

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,))
    row = cursor.fetchone()

    result = None
    if row:
        columns = [desc[0] for desc in cursor.description]
        result = dict(zip(columns, row))

    conn.close()

    return result
