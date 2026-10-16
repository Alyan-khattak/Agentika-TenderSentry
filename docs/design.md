# design.md — UI/UX & Design System
**Project:** TenderSentry MVP  
**Date:** 2026-10-17  

---

## 1. Design Goals

- **Trust and authority** — looks like a government/enterprise tool, not a startup toy.
- **Information density** — show conflicting excerpts side-by-side; no information hidden behind extra clicks.
- **Action clarity** — three decision buttons must be instantly distinguishable in colour and icon.
- **Speed** — zero build step; vanilla HTML/CSS/JS ships in minutes.

---

## 2. Visual Direction

Dark-navy primary with amber accent. Inspired by procurement/legal dashboards.  
Clean, monospaced excerpt blocks (document excerpts look like official text).

---

## 3. Colour Palette

| Token | Light value | Dark value | Usage |
|---|---|---|---|
| `--bg` | `#f4f6f9` | `#0f1520` | Page background |
| `--surface` | `#ffffff` | `#1a2235` | Cards, panels |
| `--border` | `#dde3ee` | `#2a3650` | Card borders |
| `--fg` | `#0d1b2a` | `#e8edf5` | Body text |
| `--fg-muted` | `#5a6a80` | `#7a8fa8` | Labels, metadata |
| `--accent` | `#1a56db` | `#4d7fff` | Primary buttons, links |
| `--flag` | `#dc2626` | `#ef4444` | Flag button |
| `--dismiss` | `#16a34a` | `#22c55e` | Dismiss button |
| `--escalate` | `#d97706` | `#f59e0b` | Escalate button |
| `--severity-high` | `#dc2626` | `#ef4444` | HIGH badge |
| `--severity-medium` | `#d97706` | `#f59e0b` | MEDIUM badge |
| `--severity-low` | `#16a34a` | `#22c55e` | LOW badge |

---

## 4. Typography

| Element | Font | Size | Weight |
|---|---|---|---|
| App name | Inter (Google Fonts) | 22px | 700 |
| Section heading | Inter | 16px | 600 |
| Body text | Inter | 14px | 400 |
| Document excerpts | `monospace` (system) | 13px | 400 |
| Badges / labels | Inter | 11px | 600, uppercase, letter-spacing 0.05em |
| Button label | Inter | 14px | 600 |

Line height: 1.6 for body text.

---

## 5. Layout

- **Single-column centred layout**, max-width `780px`, side gutter `24px`.
- No sidebar. No navigation bar (single-page tool).
- **Top bar:** App name left, session ID right (once analysis starts).
- Vertical section stacking with `24px` gap between panels.

### Finding Panel Layout (HITL Review)

```
┌──────────────────────────────────────────────────┐
│ Finding 2 of 3          [DEADLINE]  ● HIGH        │
├─────────────────────────┬────────────────────────┤
│ main_notice.pdf         │ schedule_a.pdf          │
│ ─────────────────────── │ ──────────────────────  │
│ "Submission Deadline:   │ "All bids must be       │
│  20 November 2026"      │  received by            │
│                         │  15 November 2026"      │
├─────────────────────────┴────────────────────────┤
│ 💬 Explanation                                    │
│ The main notice sets 20 Nov, Schedule A sets 15   │
│ Nov — a 5-day gap that invalidates bids received  │
│ between those dates.                              │
├──────────────────────────────────────────────────┤
│ ❓ Ask: "Which deadline is authoritative?"        │
├──────────────────────────────────────────────────┤
│ jev: Genuine 97%  ████████████░  Severity 88%    │
├──────────────────────────────────────────────────┤
│ Note (optional): ________________________________ │
│                                                  │
│  🚩 FLAG      ✅ DISMISS      ⬆️ ESCALATE        │
└──────────────────────────────────────────────────┘
```

---

## 6. Components

### Badge
```
.badge — border-radius 4px, padding 2px 8px, 11px uppercase
Variants: .badge-deadline (blue), .badge-requirement (purple), .badge-amount (orange), .badge-missing (grey)
Severity variants: .badge-high (red), .badge-medium (amber), .badge-low (green)
```

### Action Buttons
```
Large (min-width 120px, height 44px), rounded 8px.
.btn-flag     → red background, white text
.btn-dismiss  → green background, white text
.btn-escalate → amber background, dark text
Hover: 10% darker. Active: scale(0.97). Focus: 2px outline.
```

### Excerpt Block
```
.excerpt — monospace font, 13px, background slightly offset from surface,
           border-left 3px solid --accent, padding 12px, border-radius 4px.
```

### jev Probability Bar
```
.jev-bar — label left, percent right, gradient progress bar below (0–100%).
Colour: green if ≥ 65%, amber if 40–64%, red if < 40%.
```

### Status Spinner
```
CSS-only spinning ring, 48px, accent colour.
Centred in page. Label below: dynamic text from polling response.
```

---

## 7. Responsive Behaviour

- **≥ 640px:** Two-column excerpt layout (side-by-side).
- **< 640px:** Excerpt blocks stack vertically.
- Buttons always full-width on mobile (flex-column).
- No horizontal scroll at any width.

---

## 8. Accessibility

- Contrast ratio ≥ 4.5:1 for all text/background combinations.
- All buttons have `aria-label` attributes.
- Focus ring visible on keyboard navigation.
- Decision confirmation: brief `role="status"` toast so screen readers announce it.
- Excerpt `<pre>` blocks have `aria-label="Excerpt from [filename]"`.

---

## 9. States

| State | Visual |
|---|---|
| Upload idle | Dashed border drop zone, blue upload icon |
| Upload hover | Solid border, lighter background |
| Analysing | Full-page spinner + dynamic status label |
| HITL panel | Finding card; all 3 buttons active |
| Decision confirmed | Green toast `"Decision recorded"` (2 seconds) |
| jev unavailable | Bar replaced with `"Validation unavailable"` in muted text |
| Error | Red banner with message at top of page |
| Summary | Stat cards row + full audit table |
