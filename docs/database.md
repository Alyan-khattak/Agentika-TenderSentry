# database.md — Database Design
**Project:** TenderSentry MVP  
**Date:** 2026-10-17  

---

## 1. Database Engine

**SQLite** — file-based, zero-config, stored at `tendersentry.db` in the project root.  
Managed by Python's built-in `sqlite3` module via `database.py`.

Two tables:

---

## 2. Table: `sessions`

Tracks each analysis session (one upload = one session).

| Column | Type | Constraint | Description |
|---|---|---|---|
| `session_id` | TEXT | PRIMARY KEY | 8-char UUID fragment (e.g. `A3F7C1B2`) |
| `source_files` | TEXT | NOT NULL | JSON array of PDF filenames |
| `total_detected` | INTEGER | NOT NULL | Raw contradiction count from comparators |
| `total_validated` | INTEGER | NOT NULL | Count that passed jev genuine threshold |
| `created_at` | TEXT | NOT NULL | ISO-8601 timestamp |
| `completed_at` | TEXT | | Null until all findings reviewed |

**Example row:**
```json
{
  "session_id": "A3F7C1B2",
  "source_files": "[\"main_notice.pdf\", \"schedule_a.pdf\", \"boq.pdf\"]",
  "total_detected": 3,
  "total_validated": 3,
  "created_at": "2026-10-17T14:32:00",
  "completed_at": "2026-10-17T14:33:45"
}
```

---

## 3. Table: `audit_log`

Append-only. One row per human decision. Never deleted or updated.

| Column | Type | Constraint | Description |
|---|---|---|---|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | Internal row ID |
| `session_id` | TEXT | NOT NULL, FK → sessions | Links to parent session |
| `finding_id` | TEXT | NOT NULL | Finding UUID (generated in agent) |
| `contradiction_type` | TEXT | NOT NULL | `deadline` / `requirement` / `amount` / `missing` |
| `severity` | TEXT | NOT NULL | `HIGH` / `MEDIUM` / `LOW` |
| `doc_a` | TEXT | NOT NULL | Source document A filename |
| `excerpt_a` | TEXT | NOT NULL | Conflicting text from document A |
| `doc_b` | TEXT | NOT NULL | Source document B filename |
| `excerpt_b` | TEXT | NOT NULL | Conflicting text from document B |
| `explanation` | TEXT | NOT NULL | LLM plain-language explanation |
| `jev_genuine` | REAL | NOT NULL | jev noul score (0.0–1.0) |
| `jev_severity` | REAL | NOT NULL | jev severity score (0.0–1.0) |
| `jev_category` | TEXT | NOT NULL | jev choice answer |
| `human_decision` | TEXT | NOT NULL | `flag` / `dismiss` / `escalate` |
| `human_note` | TEXT | | Optional reviewer note (may be empty) |
| `decided_at` | TEXT | NOT NULL | ISO-8601 timestamp of decision |

**Example row:**
```json
{
  "id": 1,
  "session_id": "A3F7C1B2",
  "finding_id": "F-001",
  "contradiction_type": "deadline",
  "severity": "HIGH",
  "doc_a": "main_notice.pdf",
  "excerpt_a": "Submission Deadline: 20 November 2026, 17:00 PKT",
  "doc_b": "schedule_a.pdf",
  "excerpt_b": "All bids must be received by 15 November 2026",
  "explanation": "The main notice sets a deadline of 20 November 2026, while Schedule A states 15 November 2026 — a 5-day discrepancy that would invalidate compliant bids received between those dates.",
  "jev_genuine": 0.97,
  "jev_severity": 0.88,
  "jev_category": "deadline",
  "human_decision": "escalate",
  "human_note": "Referred to legal team",
  "decided_at": "2026-10-17T14:33:12"
}
```

---

## 4. Schema SQL

```sql
CREATE TABLE IF NOT EXISTS sessions (
    session_id   TEXT PRIMARY KEY,
    source_files TEXT NOT NULL,
    total_detected  INTEGER NOT NULL DEFAULT 0,
    total_validated INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL,
    completed_at TEXT
);

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
);
```

---

## 5. Data Handling Notes

- The database is **local only** — no network exposure.
- No personal data is stored (MVP is a demo with synthetic documents).
- `source_files` is stored as a JSON-serialised array string.
- All timestamps are UTC ISO-8601.
- The audit log is intentionally append-only; the UI has no delete or edit function.
- Database file is in `.gitignore`; it is not committed.
