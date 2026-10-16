# TenderSentry — AI Contradiction Detector for Public Tenders

An AI agent that detects contradictions and suspicious inconsistencies across public tender PDF documents. Built for the **HUMAN + AI: BETTER TOGETHER** hackathon (2026-10-17).

## Read before any work
1. `.claude/agents/standards.md` — team rules and definition of done (**read first, always**)
2. `docs/TRD.md` — full stack, libraries, env vars, constants (**wins over everything if docs disagree**)
3. `docs/PRD.md` — what to build and why
4. `docs/Architecture.md` — component diagram, LangGraph node contracts, folder structure
5. `docs/appFlow.md` — UI states, API contracts, HITL business rules
6. `docs/database.md` — SQLite schema
7. `docs/design.md` — colour tokens, typography, component specs

## Who runs the session
The main session acts as the **orchestrator** (`.claude/agents/orchestrator_agent.md`).
It plans, dispatches to specialist agents, verifies by evidence, and does **not** write product code.

| Agent | File | Owns |
|---|---|---|
| `langgraph-agent` | `langgraph_agent.md` | comparators, graph nodes (extract/compare/investigate), Pydantic entities, utils |
| `hitl-agent` | `hitl_agent.md` | `hitl_review` node, `/api/status`, `/api/decision`, audit log |
| `jev-agent` | `jev_agent.md` | `call_jev()`, question design, JevValidation, thresholds |
| `backend-agent` | `backend_agent.md` | FastAPI routes, file uploads, `main.py` |
| `frontend-agent` | `frontend_agent.md` | `static/index.html` only — no npm, no build step |
| `qa-agent` | `qa_agent.md` | tests, smoke tests, acceptance checks |
| `reviewer-agent` | `reviewer_agent.md` | code review before marking any task done |

## Project conventions (details in TRD.md and standards.md)
- **Layer order:** `constants → config_entity → component → artifact_entity`. Never import upward.
- **No hardcoded values.** Everything lives in `tendersentry/constants/__init__.py`.
- **LLM clients:** always via `get_llm()` or `get_instructor_client()` from `utils/utils.py`.
- **jev calls:** always via `call_jev()` from `utils/utils.py`.
- **Structured LLM output:** always `instructor` + a Pydantic model. No manual parsing.
- **Comparators:** deterministic only — no LLM inside `DateComparator`, `AmountComparator`, `RequirementComparator`.
- **Frontend:** single file `static/index.html`. No npm, no build step, no framework.
- **Audit log:** append-only. No DELETE or UPDATE on `audit_log` table.
- **Secrets:** `.env` only. Never log an API key. `.env` is in `.gitignore`.

## Folder structure
```
tendersentry/
├── tendersentry/
│   ├── constants/__init__.py      # all raw values — no hardcoding elsewhere
│   ├── entity/
│   │   ├── config_entity.py       # input configs (dataclasses)
│   │   └── artifact_entity.py     # output models (Pydantic)
│   ├── exception/exception.py
│   ├── logging/logger.py
│   ├── utils/utils.py             # get_llm, get_instructor_client, call_jev
│   ├── components/
│   │   ├── extractor.py           # PDF → DocumentChunk
│   │   ├── comparators.py         # DateComparator, AmountComparator, RequirementComparator
│   │   └── agent.py               # TenderState, graph nodes, build_graph()
│   └── pipeline/
│       └── analysis_pipeline.py   # thin orchestrator called by FastAPI
├── database.py                    # init_db, log_session, log_decision, get_audit_log
├── main.py                        # FastAPI app — 4 routes + static mount
├── static/index.html              # entire frontend (vanilla HTML/CSS/JS)
├── generate_docs.py               # generates 3 synthetic PDFs with planted contradictions
├── requirements.txt
├── .env                           # secrets — never commit
├── .gitignore
└── docs/                          # PRD, TRD, Architecture, appFlow, database, design, Rules, phases
```

## Commands
```bash
pip install -r requirements.txt          # install dependencies
python generate_docs.py                  # generate 3 test PDFs in artifacts/
uvicorn main:app --reload                # run API on http://localhost:8000
# open http://localhost:8000 in browser for the frontend
```

## Key env vars (copy from .env.example, fill in .env)
```
GROQ_API_KEY_1=
GROQ_API_KEY_2=
GROQ_API_KEY_3=
TYPESAFE_API_KEY=
```

## The three planted contradictions (for demo)
| # | Type | Doc A says | Doc B says |
|---|---|---|---|
| 1 | deadline | Submission by 20 November 2025 | Closing date 15 November 2025 |
| 2 | requirement | ISO 9001:2015 mandatory | ISO 9001 or equivalent accepted |
| 3 | amount | Line items sum to $847,000 | Contract value stated as $820,000 |

## LangGraph flow
```
extract → compare → investigate → hitl_review → (loop) → END
                                       ↑___________↓
```
- `interrupt()` pauses at `hitl_review`; frontend polls `/api/status`
- Human clicks Flag / Dismiss / Escalate → `POST /api/decision` → `Command(resume=decision)`

## Never
- Commit `.env`, API keys, or generated PDFs.
- Hardcode any value that already exists in `constants/__init__.py`.
- Add npm, webpack, or any build step to the frontend.
- UPDATE or DELETE rows in the `audit_log` table.
- Mark a task done without running its acceptance check.
