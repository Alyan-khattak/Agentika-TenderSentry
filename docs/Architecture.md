# Architecture.md — System Architecture
**Project:** TenderSentry MVP  
**Date:** 2026-10-17  

---

## 1. Overview

TenderSentry is a single-process FastAPI application that orchestrates a LangGraph stateful agent. The agent ingests tender PDFs, detects contradictions deterministically, explains them with an LLM, validates them with TypeSafe AI jev, and pauses for a human decision at each finding before proceeding.

**Architectural style:** Modular monolith with MLOps-style layered components.

---

## 2. High-Level Component Diagram

```
┌─────────────────────────────────────────────────────┐
│                  Browser (User)                     │
│            static/index.html  (vanilla JS)          │
└──────────────────────┬──────────────────────────────┘
                       │ HTTP (REST)
┌──────────────────────▼──────────────────────────────┐
│                  FastAPI (main.py)                  │
│  POST /api/analyse   GET /api/status/{id}           │
│  POST /api/decision  GET /api/audit-log             │
└───────┬──────────────┬──────────────────────────────┘
        │              │
┌───────▼──────┐ ┌─────▼───────────────────────────────┐
│  database.py │ │   LangGraph Agent (agent.py)         │
│  SQLite      │ │                                      │
│  audit_log   │ │  [extract]→[compare]→[investigate]  │
└──────────────┘ │         →[hitl_review]→ ...         │
                 └───┬──────────────┬──────────────────┘
                     │              │
          ┌──────────▼──┐  ┌────────▼──────────────┐
          │  Groq API   │  │  TypeSafe AI (jev)    │
          │  GPT-OSS-   │  │  POST /v1/systemone   │
          │  120B / 20B │  └───────────────────────┘
          └─────────────┘
```

---

## 3. LangGraph Agent — Node Detail

```
TenderState
│
├─ documents         : list[dict]        — raw PDF chunks
├─ contradictions    : list[dict]        — from comparators
├─ findings          : list[Finding]     — enriched + validated
├─ current_finding_idx : int
├─ human_decision    : "flag"|"dismiss"|"escalate"|None
└─ audit_log         : list[dict]

Nodes (in order):

1. extract
   IN : pdf_paths (from state init)
   OUT: documents (list of page chunks)
   Uses: PDFExtractor component

2. compare
   IN : documents
   OUT: contradictions (list[RawContradiction])
   Uses: DateComparator, AmountComparator, RequirementComparator
   ← Deterministic only; no LLM

3. investigate
   IN : contradictions[current_finding_idx]
   OUT: findings (appended with new Finding incl. jev validation)
   Uses: instructor(Groq) for FindingExplanation
         call_jev() for Noul + Score + Choice
   → Loops back to itself until all contradictions processed

4. hitl_review
   IN : findings[current_finding_idx]
   OUT: human_decision written to audit_log
   Uses: interrupt() — graph pauses here
         Command(resume=decision) — graph resumes on POST /api/decision
   → Loops back to investigate for next finding, or END
```

---

## 4. Folder Structure

```
tendersentry/                      ← repo root
├── tendersentry/                  ← application package
│   ├── __init__.py
│   ├── constants/
│   │   └── __init__.py            ← ALL raw values; no hardcoding elsewhere
│   ├── entity/
│   │   ├── config_entity.py       ← Input configs for each component
│   │   └── artifact_entity.py     ← Output Pydantic models + LLM schemas
│   ├── components/
│   │   ├── extractor.py           ← PDFExtractor (PyMuPDF)
│   │   ├── comparators.py         ← Deterministic contradiction detectors
│   │   └── agent.py               ← LangGraph graph definition + node functions
│   ├── utils/
│   │   └── utils.py               ← Key rotation, LLM/jev client factories
│   ├── exception/
│   │   └── exception.py           ← Custom exception hierarchy
│   ├── logging/
│   │   └── logger.py              ← Centralised logger (file + console)
│   └── pipeline/
│       └── analysis_pipeline.py   ← Orchestrates components; called by main.py
├── static/
│   └── index.html                 ← Complete frontend (HTML + CSS + JS)
├── main.py                        ← FastAPI app + route handlers
├── database.py                    ← SQLite audit log helpers
├── generate_docs.py               ← Generates 3 synthetic PDFs for demo
├── requirements.txt
├── .env                           ← Secrets (gitignored)
├── .gitignore
└── docs/                          ← This documentation package
    ├── PRD.md
    ├── TRD.md
    ├── Architecture.md
    ├── appFlow.md
    ├── database.md
    ├── design.md
    ├── Rules.md
    └── phases.md
```

---

## 5. Data Flow — End-to-End Sequence

```
User uploads PDFs
       ↓
POST /api/analyse
       ↓
FastAPI: spawn LangGraph thread (session_id)
       ↓
Node: extract  → ExtractionArtifact
       ↓
Node: compare  → list[RawContradiction]
       ↓
Node: investigate (per contradiction)
    ├─ instructor(Groq) → FindingExplanation
    └─ call_jev()       → JevValidation
    → builds Finding object
       ↓
Node: hitl_review  ← interrupt() fires
    → GET /api/status/{id} returns finding to frontend
       ↓
User clicks Flag / Dismiss / Escalate
       ↓
POST /api/decision  → Command(resume=decision)
    → SQLite audit log written
       ↓
Graph loops: next finding OR END
       ↓
GET /api/status/{id} returns summary
```

---

## 6. Key Architectural Decisions

| Decision | Choice | Reason |
|---|---|---|
| LLM output typing | `instructor` library | Pydantic enforcement without parsing fragility |
| Contradiction detection | Deterministic (no LLM) | Reliable, explainable, fast, defensible to judges |
| HITL mechanism | LangGraph `interrupt()` | Graph-native pause/resume; no polling hacks |
| Frontend | Vanilla JS | No npm, no build step; ships in 4 hours |
| DB | SQLite | Zero-config; audit log is append-only |
| Key rotation | `itertools.cycle` | Simple, stateless, per-call rotation |
