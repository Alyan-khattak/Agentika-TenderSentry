# phases.md — Implementation Roadmap
**Project:** TenderSentry MVP  
**Total estimated time:** 4 hours (2 engineers)  
**Date:** 2026-10-17  

---

## Phase Overview

```
PH-01 Project Skeleton & Synthetic PDFs   (30 min)
  ↓
PH-02 Extract & Compare (Deterministic)   (45 min)
  ↓
PH-03 LangGraph Agent + LLM + jev         (75 min)
  ↓
PH-04 FastAPI Backend                     (30 min)
  ↓
PH-05 Frontend (UI)                       (45 min)
  ↓
PH-06 Integration & Demo Polish           (15 min)
```

---

## PH-01 — Project Skeleton & Synthetic PDFs
**Owner:** Engineer A  
**Time:** 30 min  
**Covers:** FR-001, NFR-004, NFR-006

### Tasks

| ID | Task | Outcome |
|---|---|---|
| TASK-001 | Create folder structure per `Architecture.md` | All dirs exist with `__init__.py` |
| TASK-002 | Write `tendersentry/constants/__init__.py` | All constants defined; no hardcoding elsewhere |
| TASK-003 | Write `tendersentry/exception/exception.py` | Custom exception hierarchy |
| TASK-004 | Write `tendersentry/logging/logger.py` | Logger writes to `logs/` |
| TASK-005 | Write `.env` template + add `.gitignore` | `.env` never committed |
| TASK-006 | Write `generate_docs.py` with 3 PDFs | 3 PDFs with 3 planted contradictions |
| TASK-007 | Write `requirements.txt` | All dependencies listed |

### Exit Criteria
- `python generate_docs.py` produces `main_notice.pdf`, `schedule_a.pdf`, `boq.pdf`.
- All three PDFs open correctly in a PDF viewer.
- No secrets in any committed file.

---

## PH-02 — Extraction & Deterministic Comparators
**Owner:** Engineer A  
**Time:** 45 min  
**Covers:** FR-002, FR-003

### Tasks

| ID | Task | Outcome |
|---|---|---|
| TASK-008 | Write `entity/config_entity.py` | `ExtractorConfig`, `ComparatorConfig`, `PipelineConfig` |
| TASK-009 | Write `entity/artifact_entity.py` — extraction types | `DocumentChunk`, `ExtractionArtifact`, `RawContradiction` |
| TASK-010 | Write `components/extractor.py` | `PDFExtractor.extract()` returns `ExtractionArtifact` |
| TASK-011 | Write `components/comparators.py` — `DateComparator` | Detects deadline mismatch |
| TASK-012 | Write `components/comparators.py` — `AmountComparator` | Detects math error |
| TASK-013 | Write `components/comparators.py` — `RequirementComparator` | Detects wording contradiction |

### Exit Criteria
- Run extractor on 3 PDFs → 3 `DocumentChunk` objects with correct text.
- Run comparators on extracted text → exactly 3 `RawContradiction` objects.
- No LLM called in this phase.

---

## PH-03 — LangGraph Agent + LLM + jev Validation
**Owner:** Engineer B  
**Time:** 75 min  
**Covers:** FR-004, FR-005, FR-006, FR-010, NFR-001, NFR-002, NFR-003

### Tasks

| ID | Task | Outcome |
|---|---|---|
| TASK-014 | Write `utils/utils.py` | Key rotation, `get_llm()`, `get_instructor_client()`, `call_jev()` |
| TASK-015 | Write `entity/artifact_entity.py` — LLM + jev types | `FindingExplanation`, `JevValidation`, `Finding`, `AnalysisArtifact` |
| TASK-016 | Write `AgentConfig` in `config_entity.py` | All agent settings from constants |
| TASK-017 | Write `components/agent.py` — `TenderState` TypedDict | State schema confirmed |
| TASK-018 | Write `extract` node function | Calls `PDFExtractor`, writes to state |
| TASK-019 | Write `compare` node function | Calls comparators, writes contradictions to state |
| TASK-020 | Write `investigate` node function | Calls instructor(Groq) for `FindingExplanation`; calls `call_jev()` for validation; assembles `Finding` |
| TASK-021 | Write `hitl_review` node function | Calls `interrupt()`; on resume writes decision to `audit_log` state |
| TASK-022 | Wire graph with `StateGraph`, `SqliteSaver`, conditional edges | Graph compiles without error |

### Exit Criteria
- `graph.invoke(initial_state)` with 3 PDFs pauses at first finding (interrupt fires).
- After `Command(resume="flag")` → pauses at second finding.
- After three decisions → graph reaches END and returns `AnalysisArtifact`.
- `FindingExplanation` always returns a valid Pydantic object (instructor enforces this).
- jev timeout is caught; finding still reaches HITL.

---

## PH-04 — FastAPI Backend
**Owner:** Engineer B  
**Time:** 30 min  
**Covers:** FR-007, FR-008, FR-009, NFR-005

### Tasks

| ID | Task | Outcome |
|---|---|---|
| TASK-023 | Write `database.py` — `init_db()`, `log_session()`, `log_decision()`, `get_audit_log()` | SQLite tables created; insert + query work |
| TASK-024 | Write `pipeline/analysis_pipeline.py` | Thin orchestrator; called by FastAPI routes |
| TASK-025 | Write `main.py` — `POST /api/analyse` | Accepts PDFs, spawns graph thread, returns `session_id` |
| TASK-026 | Write `main.py` — `GET /api/status/{session_id}` | Returns `running` / `hitl_pending` / `complete` / `error` |
| TASK-027 | Write `main.py` — `POST /api/decision` | Resumes graph with human decision; writes to DB |
| TASK-028 | Write `main.py` — `GET /api/audit-log` | Returns all rows from `audit_log` table |
| TASK-029 | Add `StaticFiles` mount for `static/` | `index.html` served at `/` |

### Exit Criteria
- `uvicorn main:app --reload` starts without errors.
- `curl -X POST /api/analyse` with 3 PDFs returns `{"session_id": "..."}`.
- `/api/status/{id}` returns `hitl_pending` with finding JSON.
- `/api/decision` with a decision returns `{"ok": true}` and logs to DB.

---

## PH-05 — Frontend
**Owner:** Engineer A  
**Time:** 45 min  
**Covers:** FR-001, FR-006, FR-008, FR-009; NFR per design.md

### Tasks

| ID | Task | Outcome |
|---|---|---|
| TASK-030 | Write `static/index.html` — Upload screen with drag-drop | Files selectable; validates type + size |
| TASK-031 | Implement `POST /api/analyse` call | Shows spinner on submit |
| TASK-032 | Implement 2-second polling `GET /api/status/{id}` | Updates spinner label; transitions to HITL |
| TASK-033 | Implement HITL finding panel per `design.md` layout | Both excerpts shown; jev bar shown |
| TASK-034 | Implement Flag / Dismiss / Escalate buttons | POSTs decision; buttons disabled in-flight |
| TASK-035 | Implement Summary screen | Stat cards + audit table |
| TASK-036 | Apply colour palette, typography, badges per `design.md` | Dark-navy / amber theme; responsive |

### Exit Criteria
- Upload screen → click Analyse → spinner → finding panel → three decisions → summary.
- Both excerpts appear side-by-side on desktop, stacked on mobile.
- Buttons are disabled while POST is in-flight.
- Audit table shows all three decisions with timestamps.

---

## PH-06 — Integration, Polish & Demo Prep
**Owner:** Both engineers  
**Time:** 15 min  
**Covers:** All FRs end-to-end

### Tasks

| ID | Task | Outcome |
|---|---|---|
| TASK-037 | Full end-to-end test with 3 synthetic PDFs | All 3 contradictions surface in UI |
| TASK-038 | Verify error handling: jev offline, Groq rate limit | Graceful fallback; no crash |
| TASK-039 | Verify audit log persists after server restart | SQLite file retains rows |
| TASK-040 | Prepare 2-minute demo script | Judge can follow the story |
| TASK-041 | README.md — setup instructions | `pip install -r requirements.txt` + env vars + run |

### Exit Criteria
- Zero crashes during demo run-through.
- All 3 contradictions surface and are reviewable.
- Audit log shows all decisions.
- Demo script rehearsed.

---

## Open Blockers

| Blocker | Owner | Resolution |
|---|---|---|
| TYPESAFE_API_KEY must be valid at demo time | Both | Test before hackathon presentation |
| Groq API keys must have quota | Both | Rotate through 3 keys; emergency fallback to llama |
| `jev-latest` model name confirmed | Both | Verified from quickstart docs |
