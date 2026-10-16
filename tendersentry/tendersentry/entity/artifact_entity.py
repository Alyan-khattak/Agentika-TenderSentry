"""
TenderSentry Artifact Entities

Pydantic v2 models for component outputs and LLM schemas. These models define the contracts
for data crossing trust boundaries: PDF extractions, contradiction detections, LLM responses,
and jev validations.

Layer: `constants → config_entity → artifact_entity`. Pydantic v2 enforces strict validation.

Import pattern:
    from tendersentry.entity.artifact_entity import (
        DocumentChunk, ExtractionArtifact, RawContradiction, Finding, AnalysisArtifact
    )
"""

from typing import Optional
from pydantic import BaseModel, Field
from tendersentry.constants import (
    TYPE_DEADLINE,
    TYPE_REQUIREMENT,
    TYPE_AMOUNT,
    TYPE_MISSING,
    SEVERITY_HIGH,
    SEVERITY_MEDIUM,
    SEVERITY_LOW,
)


class DocumentChunk(BaseModel):
    """A single extracted page or text chunk from a PDF.

    Attributes:
        filename: Original PDF filename (e.g., "main_notice.pdf").
        page_num: 1-indexed page number within the PDF.
        text: Extracted text content from the page.
        tender_ref: Tender reference number extracted from page 1 text, or None if not found.
    """
    filename: str = Field(..., description="Original PDF filename")
    page_num: int = Field(..., ge=1, description="1-indexed page number")
    text: str = Field(..., description="Extracted text content")
    tender_ref: Optional[str] = Field(None, description="Tender reference number extracted from page 1 text, or None if not found")


class ExtractionArtifact(BaseModel):
    """Output of the extract node: all pages from all input PDFs.

    Attributes:
        chunks: List of DocumentChunk objects (one per page per PDF).
        total_pages: Total number of pages extracted.
    """
    chunks: list[DocumentChunk] = Field(..., description="Page chunks from all PDFs")
    total_pages: int = Field(..., ge=0, description="Total pages extracted")


class RawContradiction(BaseModel):
    """A contradiction detected by deterministic comparators (no LLM).

    Output of the compare node. These are the raw findings before LLM explanation
    and jev validation. Each comparator (DateComparator, AmountComparator,
    RequirementComparator) produces instances of this model.

    Attributes:
        contradiction_type: Type of contradiction (TYPE_DEADLINE, TYPE_REQUIREMENT, TYPE_AMOUNT, TYPE_MISSING).
        doc_a: Filename of document A.
        excerpt_a: Conflicting text or data from document A.
        doc_b: Filename of document B.
        excerpt_b: Conflicting text or data from document B.
        severity: Initial severity assessment (HIGH, MEDIUM, LOW).
        finding_id: Unique identifier for this contradiction (e.g., "F-001").
        tender_ref: Tender reference number shared by the documents in this group.
    """
    contradiction_type: str = Field(..., description="Type of contradiction (deadline/requirement/amount/missing)")
    doc_a: str = Field(..., description="Filename of document A")
    excerpt_a: str = Field(..., description="Conflicting text/data from document A")
    doc_b: str = Field(..., description="Filename of document B")
    excerpt_b: str = Field(..., description="Conflicting text/data from document B")
    severity: str = Field(..., description="Severity level (HIGH/MEDIUM/LOW)")
    finding_id: str = Field(..., description="Unique finding identifier (e.g., F-001)")
    tender_ref: Optional[str] = Field(None, description="Tender reference number for this finding's document group")


class FindingExplanation(BaseModel):
    """LLM output schema for explaining a contradiction.

    This is the exact response schema enforced by `instructor` when calling
    the LLM to explain a RawContradiction. The LLM must return structured JSON
    that parses to this Pydantic model.

    Attributes:
        explanation: Plain-language explanation of the contradiction.
        suggested_question: Question to raise with the tender issuing authority.
        severity: Severity level; LLM may adjust from the initial assessment.
    """
    explanation: str = Field(..., description="Plain-language explanation of the contradiction")
    suggested_question: str = Field(..., description="Question to raise with issuing authority")
    severity: str = Field(..., description="Severity level (may be adjusted by LLM)")


class JevValidation(BaseModel):
    """Output of jev validation call (TypeSafe AI jev-1 model).

    Result of calling the TypeSafe AI jev endpoint with a contradiction.
    If the jev call fails, jev_available is False and scores are 0.0.

    Attributes:
        jev_genuine: Noul confidence score (0.0–1.0) that the contradiction is real.
        jev_severity: Severity impact score (0.0–1.0) if the contradiction is genuine.
        jev_category: Choice answer from jev model (e.g., "deadline", "requirement").
        jev_available: False if jev call timed out or returned non-200; True if valid response.
    """
    jev_genuine: float = Field(..., ge=0.0, le=1.0, description="Noul confidence score (0.0–1.0)")
    jev_severity: float = Field(..., ge=0.0, le=1.0, description="Severity impact score (0.0–1.0)")
    jev_category: str = Field(..., description="Choice answer from jev model")
    jev_available: bool = Field(..., description="True if jev call succeeded; False if unavailable")


class Finding(BaseModel):
    """A complete finding: contradiction + explanation + validation.

    Output of the investigate node. Combines a RawContradiction, its LLM explanation,
    and its jev validation into a single Finding object ready for human review.

    Attributes:
        finding_id: Unique identifier.
        contradiction_type: Type of contradiction.
        doc_a: Filename of document A.
        excerpt_a: Conflicting text from document A.
        doc_b: Filename of document B.
        excerpt_b: Conflicting text from document B.
        explanation: LLM-generated explanation.
        suggested_question: Question to raise with issuing authority.
        severity: Severity level (may be adjusted by LLM).
        jev_genuine: Noul confidence that the contradiction is genuine.
        jev_severity: Severity impact score from jev.
        jev_category: Category answer from jev.
        jev_available: Whether jev call succeeded.
    """
    finding_id: str = Field(..., description="Unique finding identifier")
    contradiction_type: str = Field(..., description="Type of contradiction")
    doc_a: str = Field(..., description="Filename of document A")
    excerpt_a: str = Field(..., description="Conflicting text from document A")
    doc_b: str = Field(..., description="Filename of document B")
    excerpt_b: str = Field(..., description="Conflicting text from document B")
    explanation: str = Field(..., description="LLM explanation of the contradiction")
    suggested_question: str = Field(..., description="Question to raise with issuing authority")
    severity: str = Field(..., description="Severity level")
    jev_genuine: float = Field(..., ge=0.0, le=1.0, description="Noul confidence score")
    jev_severity: float = Field(..., ge=0.0, le=1.0, description="Severity impact score")
    jev_category: str = Field(..., description="Category answer from jev")
    jev_available: bool = Field(..., description="Whether jev call succeeded")
    tender_ref: Optional[str] = Field(None, description="Tender reference number for this finding's document group")


class AnalysisArtifact(BaseModel):
    """Final output of the entire analysis pipeline.

    Returned when the graph completes (all findings have been reviewed or analysis errored).

    Attributes:
        session_id: Unique session identifier.
        findings: List of all Finding objects produced by investigate node.
        total_detected: Total number of contradictions detected by compare node.
        total_validated: Count of findings where jev_genuine >= JEV_GENUINE_THRESHOLD.
        completed_at: ISO-8601 timestamp when analysis completed.
    """
    session_id: str = Field(..., description="Unique session identifier")
    findings: list[Finding] = Field(..., description="All findings from investigate node")
    total_detected: int = Field(..., ge=0, description="Total contradictions detected")
    total_validated: int = Field(..., ge=0, description="Count where jev_genuine >= threshold")
    completed_at: str = Field(..., description="ISO-8601 timestamp of completion")
