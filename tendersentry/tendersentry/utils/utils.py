"""
TenderSentry Utilities Module

Provides centralized access to LLM clients, key rotation, and jev validation.
This module is the single source for all external API calls and client instantiation.

Import pattern:
    from tendersentry.utils.utils import get_llm, get_instructor_client, call_jev, get_next_groq_key

Layer: imports from constants (no upward imports).
Secrets: loaded from .env via python-dotenv; never hardcoded.
"""

import itertools
import json
import logging as _logging
import os
from typing import Optional

import requests
import instructor
from groq import Groq
from langchain_groq import ChatGroq
from dotenv import load_dotenv, find_dotenv

from tendersentry.constants import (
    GROQ_ENV_KEYS,
    LLM_MODEL_PRIMARY,
    LLM_TEMPERATURE,
    LLM_MAX_TOKENS,
    JEV_ENV_KEY,
    JEV_ENDPOINT,
    JEV_MODEL,
    JEV_TIMEOUT_SECONDS,
    JEV_Q_GENUINE,
    JEV_Q_SEVERITY,
    JEV_Q_CATEGORY,
    STATUS_JEV_UNAVAILABLE,
)
from tendersentry.entity.artifact_entity import JevValidation
from tendersentry.logging.logger import logging

# Load .env at module level; use find_dotenv() to locate it from project root
load_dotenv(find_dotenv())


# ============================================================================
# Groq API Key Rotation
# ============================================================================

# Build list of valid Groq API keys from env, filtering out empty/missing ones
_groq_keys_from_env = [os.environ.get(key_name, "") for key_name in GROQ_ENV_KEYS]
_groq_keys_valid = [k for k in _groq_keys_from_env if k]  # Drop empty strings

if not _groq_keys_valid:
    logging.warning(
        "No valid Groq API keys found in env vars %s. "
        "get_next_groq_key() will return empty string.",
        GROQ_ENV_KEYS
    )

# Cycle through valid keys; ponytail: global cycle, upgrade to per-request if throughput matters
_groq_key_cycle = itertools.cycle(_groq_keys_valid) if _groq_keys_valid else iter([])
_groq_key_index = 0  # Track index for logging (not the key itself)


def get_next_groq_key() -> str:
    """
    Return the next Groq API key from the rotation cycle.

    Rotates through GROQ_API_KEY_1, GROQ_API_KEY_2, GROQ_API_KEY_3 as defined
    in constants. Logs the key index (not the value).

    Returns:
        str: Next Groq API key from rotation cycle.

    Raises:
        StopIteration: If no valid keys are loaded (unlikely in normal operation).
    """
    global _groq_key_index

    if not _groq_keys_valid:
        raise ValueError(
            "No Groq API keys available. Check .env file contains "
            "at least one of: GROQ_API_KEY_1, GROQ_API_KEY_2, GROQ_API_KEY_3"
        )

    key = next(_groq_key_cycle)
    current_index = _groq_key_index % len(_groq_keys_valid)
    _groq_key_index += 1

    logging.debug(f"Using Groq API key index {current_index}")
    return key


def get_llm(model: Optional[str] = None) -> ChatGroq:
    """
    Return a ChatGroq LLM instance with the next API key from rotation.

    Used by LangGraph nodes that need to call the LLM for structured reasoning.
    Each call uses the next key from the rotation cycle to distribute load.

    Args:
        model: LLM model name (default: LLM_MODEL_PRIMARY from constants).
               Example: "openai/gpt-oss-120b"

    Returns:
        ChatGroq: Configured ChatGroq instance with next API key, ready for inference.

    Raises:
        ValueError: If no Groq API keys are available in .env.
    """
    model = model or LLM_MODEL_PRIMARY

    return ChatGroq(
        model=model,
        api_key=get_next_groq_key(),
        temperature=LLM_TEMPERATURE,
        max_tokens=LLM_MAX_TOKENS,
    )


def get_instructor_client() -> instructor.Instructor:
    """
    Return an instructor-wrapped Groq client for structured LLM output.

    Used by LangGraph nodes that require structured Pydantic responses.
    The Groq client is wrapped with instructor to enforce JSON schema
    validation on all LLM responses.

    Returns:
        instructor.Instructor: Groq client wrapped with instructor mode=JSON,
                              ready for structured output calls.

    Raises:
        ValueError: If no Groq API keys are available in .env.
    """
    raw_groq_client = Groq(api_key=get_next_groq_key())
    return instructor.from_groq(raw_groq_client, mode=instructor.Mode.JSON)


# ============================================================================
# TypeSafe AI jev Validation
# ============================================================================

def call_jev(finding_context: str, finding_type: str) -> JevValidation:
    """
    Call TypeSafe AI jev-1 model to validate a contradiction finding.

    Sends a structured request to the jev endpoint with three parallel questions:
    1. is_genuine (noul): confidence that the contradiction is real (0–1)
    2. severity_score (score): impact severity if genuine (0–1)
    3. category (choice): type of contradiction (deadline/requirement/amount/missing/other)

    On failure (timeout, non-200 status, parse error), logs a warning and returns
    JevValidation with all scores at 0.0 and jev_available=False. This ensures
    that findings are never silently dropped due to API unavailability.

    Args:
        finding_context: String describing the contradiction (excerpts + context).
        finding_type: Contradiction type (e.g., "deadline", "amount", "requirement").

    Returns:
        JevValidation: Pydantic model with:
            - jev_genuine: float (0–1) — confidence the contradiction is genuine
            - jev_severity: float (0–1) — severity impact score
            - jev_category: str — category answer from jev model
            - jev_available: bool — True if call succeeded, False if unavailable

    Raises:
        None — always returns JevValidation, never raises.
    """
    api_key = os.environ.get(JEV_ENV_KEY, "")

    if not api_key:
        logging.warning(
            "jev API key not found in env var %s. "
            "Returning JevValidation with jev_available=False.",
            JEV_ENV_KEY
        )
        return JevValidation(
            jev_genuine=0.0,
            jev_severity=0.0,
            jev_category=STATUS_JEV_UNAVAILABLE,
            jev_available=False,
        )

    # Construct the three jev questions
    payload = {
        "model": JEV_MODEL,
        "state": finding_context,  # Context string with both excerpts
        "questions": {
            JEV_Q_GENUINE: {
                "type": "noul",
                "instructions": (
                    "Is this a genuine factual contradiction in the tender document "
                    "that would confuse or mislead a bidder responding to this tender?"
                ),
            },
            JEV_Q_SEVERITY: {
                "type": "score",
                "instructions": "How severely would this contradiction harm a bidder who relies on this tender?",
                "criteria": [
                    "Trivial — wording difference, no material impact on the bid",
                    "Moderate — could cause confusion but bidder can resolve it",
                    "Serious — bidder cannot comply with both documents simultaneously",
                ],
            },
            JEV_Q_CATEGORY: {
                "type": "choice",
                "instructions": "What is the primary type of this contradiction?",
                "criteria": {
                    "deadline": "A date, time, or submission window that differs between documents",
                    "requirement": "A qualification, certification, or eligibility rule that differs",
                    "amount": "A financial figure, sum, or calculation that is inconsistent",
                    "missing_reference": "A document references another that is absent or unnamed",
                    "other": "A contradiction that does not fit the above categories",
                },
            },
        },
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        # POST to jev endpoint with timeout
        response = requests.post(
            JEV_ENDPOINT,
            json=payload,
            headers=headers,
            timeout=JEV_TIMEOUT_SECONDS,
        )
        response.raise_for_status()  # Raise on 4xx, 5xx status codes

        data = response.json()
        answers = data.get("answers", {})

        # Parse answers by question id
        is_genuine_answer = answers.get(JEV_Q_GENUINE, {})
        severity_answer = answers.get(JEV_Q_SEVERITY, {})
        category_answer = answers.get(JEV_Q_CATEGORY, {})

        # Extract typed values from each answer
        jev_genuine = is_genuine_answer.get("noul", 0.0)
        jev_severity = severity_answer.get("score", 0.0)
        jev_category = category_answer.get("choice", STATUS_JEV_UNAVAILABLE)

        # Validate ranges
        if not (0.0 <= jev_genuine <= 1.0):
            logging.warning(
                f"jev is_genuine score out of range: {jev_genuine}. Clamping to [0, 1]."
            )
            jev_genuine = max(0.0, min(1.0, jev_genuine))

        if not (0.0 <= jev_severity <= 1.0):
            logging.warning(
                f"jev severity_score out of range: {jev_severity}. Clamping to [0, 1]."
            )
            jev_severity = max(0.0, min(1.0, jev_severity))

        logging.info(
            f"jev validation succeeded: genuine={jev_genuine:.2f}, "
            f"severity={jev_severity:.2f}, category={jev_category}"
        )

        return JevValidation(
            jev_genuine=jev_genuine,
            jev_severity=jev_severity,
            jev_category=jev_category,
            jev_available=True,
        )

    except requests.exceptions.Timeout:
        logging.warning(
            f"jev API timeout ({JEV_TIMEOUT_SECONDS}s). "
            "Returning fallback with jev_available=False."
        )
        return JevValidation(
            jev_genuine=0.0,
            jev_severity=0.0,
            jev_category=STATUS_JEV_UNAVAILABLE,
            jev_available=False,
        )

    except requests.exceptions.HTTPError as e:
        logging.warning(
            f"jev API returned HTTP {e.response.status_code}. "
            "Returning fallback with jev_available=False."
        )
        return JevValidation(
            jev_genuine=0.0,
            jev_severity=0.0,
            jev_category=STATUS_JEV_UNAVAILABLE,
            jev_available=False,
        )

    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logging.warning(
            f"jev API response parse error: {type(e).__name__}. "
            "Returning fallback with jev_available=False."
        )
        return JevValidation(
            jev_genuine=0.0,
            jev_severity=0.0,
            jev_category=STATUS_JEV_UNAVAILABLE,
            jev_available=False,
        )

    except Exception as e:
        logging.warning(
            f"Unexpected error calling jev API: {type(e).__name__}: {str(e)[:100]}. "
            "Returning fallback with jev_available=False."
        )
        return JevValidation(
            jev_genuine=0.0,
            jev_severity=0.0,
            jev_category=STATUS_JEV_UNAVAILABLE,
            jev_available=False,
        )
