# appFlow.md — Application & User Flow
**Project:** TenderSentry MVP  
**Date:** 2026-10-17  

---

## 1. Screen Inventory

| Screen / State | Description |
|---|---|
| Upload Screen | Default landing state; user selects PDF files |
| Analysing State | Spinner shown while agent runs extract → compare → investigate |
| HITL Review Screen | One finding shown at a time; human clicks Flag / Dismiss / Escalate |
| Summary Screen | Final counts + audit log table |

All states exist within a **single HTML page** (`static/index.html`). Sections are shown/hidden with JavaScript; no page navigation.

---

## 2. Complete User Journey

### Step 1 — Upload

- User lands on the page and sees a file-drop area.
- Selects 2–5 PDF files (or drags and drops).
- Clicks **"Analyse Tender"** button.
- Frontend validates: `.pdf` extension only, max 10 MB each.
- On validation failure: red inline error message shown; upload blocked.
- On success: `POST /api/analyse` with `multipart/form-data`.

### Step 2 — Analysing

- Upload screen is replaced by a full-page spinner + status message: `"Extracting documents… Comparing clauses… Validating findings…"`
- Frontend polls `GET /api/status/{session_id}` every 2 seconds.
- The poll response can be:
  - `{"status": "running"}` → keep spinner
  - `{"status": "hitl_pending", "finding": {...}}` → go to Step 3
  - `{"status": "complete", "summary": {...}}` → go to Step 4
  - `{"status": "error", "message": "..."}` → show error screen

### Step 3 — HITL Review (repeats per finding)

- Finding panel slides in showing:
  - Finding number (e.g. "Finding 2 of 3")
  - Contradiction type badge: `DEADLINE` / `REQUIREMENT` / `AMOUNT`
  - Severity badge: `HIGH` / `MEDIUM` / `LOW`
  - **Document A** name + excerpt (highlighted)
  - **Document B** name + excerpt (highlighted)
  - Plain-language explanation (from GPT-OSS-120B)
  - Suggested question to raise with the issuing authority
  - jev validation bar: genuine probability (0–100%), severity score
- Three action buttons:
  - 🚩 **Flag** — Mark for official record; bidder should be notified
  - ✅ **Dismiss** — Reviewer accepts this as non-material or a typo
  - ⬆️ **Escalate** — Refer to senior officer or legal team
- Optional: short text note field before confirming decision.
- User clicks a button → `POST /api/decision` with `{session_id, finding_id, decision, note}`.
- Frontend shows brief confirmation toast → next finding loads (polls again).
- If all findings are reviewed → goes to Step 4.

### Step 4 — Summary

Summary panel shows:
- Total contradictions detected
- Total that passed jev validation (jev_genuine ≥ threshold)
- Count flagged / dismissed / escalated
- Full audit log table:
  - Columns: Finding ID | Type | Severity | jev Score | Decision | Note | Timestamp
- **"New Analysis"** button resets to Step 1.

---

## 3. API Endpoints (Frontend ↔ Backend)

| Method | Path | Request | Response |
|---|---|---|---|
| POST | `/api/analyse` | multipart PDFs | `{session_id}` |
| GET | `/api/status/{session_id}` | — | `{status, finding?, summary?}` |
| POST | `/api/decision` | `{session_id, finding_id, decision, note}` | `{ok: true}` |
| GET | `/api/audit-log` | — | `[{...audit rows}]` |

---

## 4. Error States

| Error | User sees |
|---|---|
| Non-PDF file selected | Inline: "Only PDF files are accepted." |
| File > 10 MB | Inline: "File exceeds 10 MB limit." |
| Groq API exhausted | Toast: "Analysis failed — LLM unavailable. Try again shortly." |
| jev unavailable | Finding still shown; jev bar replaced with "Validation unavailable" label |
| Upload timeout | Toast: "Upload timed out. Check connection and retry." |
| Unknown server error | Toast: "Something went wrong. Check server logs." |

---

## 5. State Machine

```
[UPLOAD] ──upload+POST──▶ [ANALYSING] ──hitl_pending──▶ [HITL_REVIEW]
                                │                              │
                                │                         (loops per finding)
                                │                              │
                          error │                        all reviewed
                                ▼                              ▼
                          [ERROR] ◀────────────────── [SUMMARY]
                                                            │
                                                      "New Analysis"
                                                            ▼
                                                       [UPLOAD]
```

---

## 6. HITL Decision Business Rules

- Every finding must receive exactly one decision before the agent advances.
- A decision cannot be undone via the UI (audit log is append-only).
- The optional note is stored alongside the decision; it may be empty.
- All three actions (flag / dismiss / escalate) are treated as valid completions; none blocks the agent.
