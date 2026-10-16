# Rules.md — AI Development Rules
**Project:** TenderSentry MVP  
**For:** Any AI coding assistant (Cursor, Copilot, Claude Code, etc.)  
**Date:** 2026-10-17  

---

## 1. Read the Docs First

Before writing or editing any code, read the relevant documents:
- `Architecture.md` for structure and data flow.
- `TRD.md` for approved stack and dependencies.
- `database.md` for the exact schema.
- `appFlow.md` for endpoint contracts and state transitions.

Do not invent or assume anything that contradicts these documents.

---

## 2. Architecture Rules

- The layered pattern is **mandatory**: `constants → config_entity → component → artifact_entity`.
- Every component takes a typed `Config` dataclass and returns a typed `Artifact` Pydantic model.
- **No hardcoded values anywhere except `constants/__init__.py`.**
- `utils/utils.py` holds only shared utility functions (key rotation, LLM factory, jev caller). No business logic.
- `exception/exception.py` holds only exception class definitions — no logic.
- `pipeline/analysis_pipeline.py` orchestrates components; `main.py` calls only the pipeline.

---

## 3. LLM Rules

- Always use `get_llm()` or `get_instructor_client()` from `utils/utils.py` — never instantiate Groq/ChatGroq directly.
- Model priority: GPT-OSS-120B → GPT-OSS-20B → llama-3.1-8b-instant.
- Every LLM call for structured output **must** go through `instructor` and return a validated Pydantic model.
- Do not parse LLM text output manually. If structured output fails, raise `LLMError`.

---

## 4. Comparator Rules

- The three deterministic comparators (date, amount, requirement) **must not call any LLM**.
- Detection = deterministic code only. LLMs are for explanation only.
- If a comparator cannot parse a value, it logs a warning and skips that field — it does not crash.

---

## 5. jev Validation Rules

- The jev tool always fires three questions in one API call: `is_genuine` (Noul), `severity` (Score), `category` (Choice).
- If jev returns a non-200 response or times out, catch the error, log it, and set `jev_genuine = 0.0` and `jev_category = "jev_unavailable"` on the Finding.
- The HITL node must still present the finding to the human — jev failure never silently drops a finding.
- Never hardcode the jev endpoint or model name; read from constants.

---

## 6. Security Rules

- **Never** commit `.env` or any file containing API keys.
- `.env` must be in `.gitignore` before the first commit.
- Never log API key values — log only key index or `"key_N"`.
- Input validation: reject non-`.pdf` files and files > 10 MB before they reach the agent.
- SQLite audit log: no DELETE or UPDATE exposed via any API endpoint.

---

## 7. LangGraph Rules

- The graph must use `SqliteSaver` as checkpointer — not `MemorySaver`.
- `hitl_review` node must call `interrupt()` and wait for `Command(resume=decision)`.
- Do not use `threading` or `asyncio.create_task` to run the graph; use LangGraph's own threading via `graph.stream()` or `graph.invoke()` with a thread config.
- `TenderState` TypedDict is the single source of truth for graph state — do not pass extra dicts.

---

## 8. Database Rules

- Only `database.py` may read or write to SQLite.
- Schema is defined once in `database.py`'s `init_db()` function with `CREATE TABLE IF NOT EXISTS`.
- All inserts use parameterised queries — no f-string SQL.
- `audit_log` is append-only. No delete or update route may be added without explicit approval.

---

## 9. Frontend Rules

- The entire frontend lives in `static/index.html` — one file, no npm, no build.
- All CSS and JS are inline (no external files except Google Fonts CDN).
- State is managed in a plain JS object; no React, no Vue, no framework.
- Polling interval for `/api/status/{id}`: 2 seconds. Clear the interval on terminal state.
- Buttons must be disabled while a decision POST is in-flight to prevent double-submit.

---

## 10. General Rules

- Match the naming conventions of the existing codebase exactly.
- Do not refactor code that is not related to the current task.
- Do not add dependencies not in `requirements.txt` without approval.
- Every new file must have a module-level docstring stating its purpose.
- Log at INFO level for normal flow; ERROR level for exceptions.
- If a task is incomplete, leave a `# TODO:` comment — do not pretend it is done.
- Update `docs/` if a confirmed architectural decision changes.
