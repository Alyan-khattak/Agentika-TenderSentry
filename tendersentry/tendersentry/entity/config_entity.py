"""
TenderSentry Configuration Entities

Dataclass configs for each component in the pipeline. These are internal configuration objects
(not trust-boundary models) that hold settings, paths, and thresholds.

Layer: `constants → config_entity`. No hardcoded values; all come from constants.

Import pattern:
    from tendersentry.entity.config_entity import ExtractorConfig, PipelineConfig, make_pipeline_config
"""

from dataclasses import dataclass
from tendersentry.constants import (
    ARTIFACTS_DIR,
    LLM_MODEL_PRIMARY,
    LLM_TEMPERATURE,
    LLM_MAX_TOKENS,
    JEV_ENDPOINT,
    JEV_MODEL,
    JEV_TIMEOUT_SECONDS,
    JEV_GENUINE_THRESHOLD,
    DATE_TOLERANCE_DAYS,
    AMOUNT_TOLERANCE_PCT,
    REQUIREMENT_KEYWORD_PAIRS,
    DB_PATH,
)


@dataclass
class ExtractorConfig:
    """Configuration for PDFExtractor component.

    Attributes:
        pdf_paths: List of absolute paths to PDF files to extract.
        artifacts_dir: Output directory for extracted artifacts.
    """
    pdf_paths: list[str]
    artifacts_dir: str


@dataclass
class ComparatorConfig:
    """Configuration for deterministic contradiction comparators.

    Attributes:
        date_tolerance_days: Tolerance in days for date comparisons (0 = exact match).
        amount_tolerance_pct: Tolerance as percentage for amount comparisons (0.01 = 1%).
        requirement_keyword_pairs: List of keyword pairs that signal conflicting requirements.
    """
    date_tolerance_days: int
    amount_tolerance_pct: float
    requirement_keyword_pairs: list


@dataclass
class AgentConfig:
    """Configuration for the LangGraph agent (LLM + jev validation).

    Attributes:
        llm_model: Model ID for the primary LLM (e.g., openai/gpt-oss-120b).
        llm_temperature: Temperature for LLM inference (0.0–1.0).
        llm_max_tokens: Maximum tokens for LLM response.
        jev_endpoint: HTTP endpoint for TypeSafe AI jev service.
        jev_model: Model name for jev validation (e.g., jev-latest).
        jev_timeout: HTTP timeout in seconds for jev calls.
        jev_genuine_threshold: Confidence threshold for jev noul score (0.0–1.0).
        db_path: Path to SQLite audit log database.
    """
    llm_model: str
    llm_temperature: float
    llm_max_tokens: int
    jev_endpoint: str
    jev_model: str
    jev_timeout: int
    jev_genuine_threshold: float
    db_path: str


@dataclass
class PipelineConfig:
    """Root configuration for the entire analysis pipeline.

    Combines all component configs plus session metadata.

    Attributes:
        pdf_paths: Input PDFs to analyze.
        session_id: Unique session identifier.
        extractor: PDFExtractor config.
        comparator: Contradiction comparator config.
        agent: LangGraph agent config.
    """
    pdf_paths: list[str]
    session_id: str
    extractor: ExtractorConfig
    comparator: ComparatorConfig
    agent: AgentConfig


def make_pipeline_config(pdf_paths: list[str], session_id: str) -> PipelineConfig:
    """Factory function to create a PipelineConfig from constants and arguments.

    Builds all sub-configs using values from tendersentry.constants, ensuring
    no hardcoded thresholds or model names in the pipeline layer.

    Args:
        pdf_paths: List of absolute paths to PDFs to analyze.
        session_id: Unique session identifier (e.g., from new_session_id()).

    Returns:
        PipelineConfig ready to pass to analysis_pipeline.run().
    """
    extractor_cfg = ExtractorConfig(
        pdf_paths=pdf_paths,
        artifacts_dir=ARTIFACTS_DIR,
    )

    comparator_cfg = ComparatorConfig(
        date_tolerance_days=DATE_TOLERANCE_DAYS,
        amount_tolerance_pct=AMOUNT_TOLERANCE_PCT,
        requirement_keyword_pairs=REQUIREMENT_KEYWORD_PAIRS,
    )

    agent_cfg = AgentConfig(
        llm_model=LLM_MODEL_PRIMARY,
        llm_temperature=LLM_TEMPERATURE,
        llm_max_tokens=LLM_MAX_TOKENS,
        jev_endpoint=JEV_ENDPOINT,
        jev_model=JEV_MODEL,
        jev_timeout=JEV_TIMEOUT_SECONDS,
        jev_genuine_threshold=JEV_GENUINE_THRESHOLD,
        db_path=DB_PATH,
    )

    return PipelineConfig(
        pdf_paths=pdf_paths,
        session_id=session_id,
        extractor=extractor_cfg,
        comparator=comparator_cfg,
        agent=agent_cfg,
    )
