"""
TenderSentry Constants Module

All raw values used throughout the project are defined here. This is the foundation layer
(constants → config_entity → component → artifact_entity); no hardcoded values appear
elsewhere in the codebase. Every threshold, model name, path, URL, and message comes from
this module.

Import pattern:
    from tendersentry.constants import (GROQ_ENV_KEYS, LLM_MODEL_PRIMARY, ...)

Never:
- Hardcode a value that lives here
- Import from tendersentry modules above (this is the base layer)
- Add secrets here (only env var NAMES, never values)
"""

# ============================================================================
# Groq / LLM Configuration
# ============================================================================

# Environment variable names for Groq API key rotation (keys are in .env, names here)
GROQ_ENV_KEYS = ["GROQ_API_KEY_1", "GROQ_API_KEY_2", "GROQ_API_KEY_3"]

# Model selection (from TRD.md approved stack)
# IMP: Groq hosts these OSS models; switching providers requires changes throughout utils.py
LLM_MODEL_PRIMARY = "openai/gpt-oss-120b"      # 120B MoE, 131K context, best reasoning
LLM_MODEL_FALLBACK = "openai/gpt-oss-20b"      # Fallback: smaller, faster
LLM_MODEL_EMERGENCY = "llama-3.1-8b-instant"   # Last resort: always available

# Inference parameters
LLM_TEMPERATURE = 0.1       # Low temperature for consistent, deterministic output
LLM_MAX_TOKENS = 4096       # Sufficient for Finding explanations and metadata
LLM_MAX_RETRIES = 2         # Instructor retries before raising LLMError


# ============================================================================
# TypeSafe AI jev Validation
# ============================================================================

# Environment variable for jev API key (secret, not hardcoded)
JEV_ENV_KEY = "TYPESAFE_API_KEY"

# Endpoint and model configuration
JEV_ENDPOINT = "https://api.typesafe.ai/v1/systemone"
JEV_MODEL = "jev-latest"

# Request/response handling
JEV_TIMEOUT_SECONDS = 10          # HTTP timeout for jev calls
JEV_GENUINE_THRESHOLD = 0.5       # Noul score ≥ 0.5 → Finding is genuine

# jev question identifiers (sent in payload, responses keyed by these)
JEV_Q_GENUINE = "is_genuine"      # Noul: confidence that contradiction is real (0-1)
JEV_Q_SEVERITY = "severity_score" # Score: impact if genuine (0-1)
JEV_Q_CATEGORY = "category"       # Choice: type of contradiction (string)


# ============================================================================
# Comparator Thresholds
# ============================================================================

# Date comparison: tolerance for same deadline in different documents
# IMP: Set to 0 for zero tolerance (exact match required); increase if fuzzy matching needed
DATE_TOLERANCE_DAYS = 0

# Amount/math comparison: tolerance for line-item sums vs. stated total
# Example: if items sum to $847,000 and total says $820,000, diff is 3.2% → flag if > 1%
AMOUNT_TOLERANCE_PCT = 0.01  # 1% tolerance
AMOUNT_MIN_LINE_ITEMS = 3   # A document needs at least this many non-total amounts to be treated as a BOQ

# Requirement matching: keyword pairs that conflict
# DateComparator matches these; if doc A has form 1 and doc B has form 2 → flag
REQUIREMENT_KEYWORD_PAIRS = [
    ("ISO 9001:2015", "ISO 9001"),      # Specific version vs. generic standard
    ("mandatory", "optional"),            # Mutually exclusive requirement strength
    ("mandatory", "or equivalent"),       # Hard requirement vs. flexible
]


# ============================================================================
# Contradiction Types (used in RawContradiction, Finding)
# ============================================================================

TYPE_DEADLINE = "deadline"      # DateComparator: conflicting submission/closing dates
TYPE_REQUIREMENT = "requirement"  # RequirementComparator: conflicting ISO/mandatory/optional
TYPE_AMOUNT = "amount"          # AmountComparator: stated total ≠ sum of line items
TYPE_MISSING = "missing"        # Data not found in one or more documents


# ============================================================================
# Severity Levels (used in Finding.severity)
# ============================================================================

SEVERITY_HIGH = "HIGH"      # Critical: directly affects tender validity or cost
SEVERITY_MEDIUM = "MEDIUM"  # Significant: ambiguous language or delayed timeline
SEVERITY_LOW = "LOW"        # Minor: potential inconsistency, may be clarifiable


# ============================================================================
# Human Decisions (hitl_review output)
# ============================================================================

DECISION_FLAG = "flag"        # Human confirmed: contradiction is genuine and material
DECISION_DISMISS = "dismiss"  # Human rejected: contradiction is false or immaterial
DECISION_ESCALATE = "escalate"  # Human escalated: requires legal or procurement review


# ============================================================================
# File Paths (relative to repo root)
# ============================================================================

DB_PATH = "tendersentry.db"     # SQLite audit log location
ARTIFACTS_DIR = "artifacts"     # Output directory for generated PDFs and logs
LOGS_DIR = "logs"               # Application logs
STATIC_DIR = "static"           # Frontend assets (index.html, etc.)


# ============================================================================
# API Configuration
# ============================================================================

# File upload limits (from TRD.md section 8)
MAX_FILE_SIZE_MB = 10
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024  # 10,485,760 bytes

# Allowed MIME types for upload
ALLOWED_EXTENSIONS = {".pdf"}

# Frontend polling interval (from appFlow.md)
POLL_INTERVAL_SECONDS = 2  # Frontend polls /api/status/{session_id} every 2 seconds


# ============================================================================
# Agent Status Values (used in analysis state machine)
# ============================================================================

STATUS_RUNNING = "running"                # Graph is executing (extract → compare → investigate)
STATUS_HITL_PENDING = "hitl_pending"      # Paused at hitl_review, awaiting human decision
STATUS_COMPLETE = "complete"              # Graph completed all findings successfully
STATUS_ERROR = "error"                    # Graph halted due to unrecoverable error
STATUS_JEV_UNAVAILABLE = "jev_unavailable"  # jev API unavailable; findings still presented


# ============================================================================
# PDF Generation (for generate_docs.py — synthetic test documents)
# ============================================================================

# Output directory for generated PDFs
PDF_OUTPUT_DIR = "artifacts"

# File names of the three test PDFs (with planted contradictions)
PDF_MAIN_NOTICE = "main_notice.pdf"       # Tender main notice: contains deadline #1, ISO, line items
PDF_SCHEDULE_A = "schedule_a.pdf"         # Schedule A: contains deadline #2, amount mismatch
PDF_BOQ = "boq.pdf"                       # Bill of Quantities: contains ISO variant, total amount


# ============================================================================
# Tender Reference Extraction
# ============================================================================

# Regex pattern to extract tender reference numbers from document text
# Matches patterns like: RFT: ABC123, REF: PKG-2025-047, Tender Reference: PKG-2025-047, etc.
# Captures the reference (group 1) as uppercase alphanumeric with hyphens/slashes, minimum 4 chars
# The pattern prioritizes finding "PKG-", "RFT:", "Ref:" prefixes over generic "Tender/Reference/Contract"
TENDER_REF_RE = r'(?:RFT|ITT|RFP|EOI|IFB|Tender\s+Reference|Reference\s*No|Contract\s*No|Ref\.?|REF)\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-/]{3,29})'
