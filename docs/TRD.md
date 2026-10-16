# TRD.md — Technical Requirements Document
**Project:** TenderSentry MVP  
**Date:** 2026-10-17  

---

## 1. Approved Technology Stack

| Layer | Technology | Rationale |
|---|---|---|
| Backend framework | FastAPI (Python 3.11+) | Async, fast, automatic OpenAPI docs |
| Agent orchestration | LangGraph | Stateful graph, `interrupt()` for HITL, built-in SQLite checkpointer |
| LLM provider | Groq Cloud API | Free-tier fast inference; hosts GPT-OSS-120B and fallbacks |
| LLM — primary | `openai/gpt-oss-120b` | 120B MoE, 131K context, best reasoning |
| LLM — fallback | `openai/gpt-oss-20b` | Faster, smaller, same Groq API |
| LLM — emergency | `llama-3.1-8b-instant` | Always available on Groq free tier |
| Structured LLM output | `instructor` library wrapping Groq | Enforces Pydantic schemas on LLM responses |
| Validation model | TypeSafe AI jev-1 (`jev-latest`) | Typed decision model — noul/score/choice primitives |
| PDF extraction | PyMuPDF (`fitz`) | Page-level text extraction; handles multi-page PDFs |
| PDF generation (synthetic) | `reportlab` | Generates 3 test PDFs with planted contradictions |
| Audit database | SQLite via `sqlite3` stdlib | Zero-config, sufficient for MVP |
| Frontend | Vanilla HTML / CSS / JS | No build step; single `static/index.html` |
| Environment config | `python-dotenv` | Loads `.env` at startup |

---

## 2. External API Integrations

### 2.1 Groq Cloud API
- **Endpoint:** `https://api.groq.com/openai/v1/`
- **Auth:** `Authorization: Bearer <GROQ_API_KEY>`
- **Key rotation:** `itertools.cycle` over `GROQ_API_KEY_1`, `GROQ_API_KEY_2`, `GROQ_API_KEY_3`
- **Client:** `langchain_groq.ChatGroq` (for LangGraph) + `groq.Groq` wrapped by `instructor` (for typed outputs)

### 2.2 TypeSafe AI jev-1
- **Endpoint:** `POST https://api.typesafe.ai/v1/systemone`
- **Auth:** `Authorization: Bearer <TYPESAFE_API_KEY>`
- **Model:** `jev-latest`
- **Failure mode:** If jev returns non-200 or times out, the finding is still passed to HITL with `jev_genuine=0.0` and a `"jev_unavailable"` flag; the human decides anyway.

---

## 3. Environment Variables

```
# .env (never commit this file)
GROQ_API_KEY_1=gsk_...
GROQ_API_KEY_2=gsk_...
GROQ_API_KEY_3=gsk_...
TYPESAFE_API_KEY=ts_...
```

---

## 4. Architecture Style

- **Monolith** — single FastAPI process, no microservices.
- **MLOps-inspired layered structure:**  
  `constants → config_entity → component → artifact_entity`  
  Each component takes a typed Config, returns a typed Artifact. No hardcoded values.

---

## 5. LangGraph Agent Design

| Node | Type | Description |
|---|---|---|
| `extract` | Regular | PDFExtractor component → ExtractionArtifact |
| `compare` | Regular | Deterministic comparators → list[RawContradiction] |
| `investigate` | Regular | LLM (GPT-OSS-120B via instructor) + jev validation → list[Finding] |
| `hitl_review` | Interrupt | `interrupt()` pauses graph; frontend POSTs human decision; `Command(resume=decision)` continues |

**Checkpointer:** `SqliteSaver` — graph state survives server restarts.

---

## 6. Deterministic Comparators (no LLM)

| Comparator | Method |
|---|---|
| Deadline | `dateutil.parser` on all date strings; compare with tolerance = 0 days |
| Amount / Math | Regex extract all `$NNN,NNN` patterns; sum line items, compare to stated total (1% tolerance) |
| Requirements | Keyword pairs: `["ISO 9001", "or equivalent"]`, `["mandatory", "optional"]` |

LLMs are used only for explanation and validation — not detection. This is explicitly a feature.

---

## 7. Performance Requirements

| Metric | Target | Notes |
|---|---|---|
| End-to-end analysis (3 PDFs) | < 60 seconds | Groq inference is fast; bottleneck is jev + LLM |
| HITL response render | < 500 ms | Frontend polls `/api/status/{session_id}` |
| PDF upload | < 5 seconds | Max 10 MB per file |

---

## 8. Security (MVP scope)

- All secrets via `.env` only; `.env` in `.gitignore`.
- No user authentication for MVP (single-user demo tool).
- Input validation: file type check (`.pdf` only), size check (max 10 MB).
- SQLite is local; no network exposure of audit data.

---

## 9. Testing Strategy (MVP)

- `generate_docs.py` produces known PDFs with known contradictions → deterministic assertions.
- Manual end-to-end test: upload 3 PDFs → verify all 3 contradictions surface.
- No automated test suite required for hackathon MVP.

---

## 10. Dependencies (`requirements.txt`)

```
fastapi
uvicorn[standard]
python-dotenv
langchain-groq
langgraph
instructor
groq
pymupdf
reportlab
python-dateutil
requests
pydantic>=2.0
```
