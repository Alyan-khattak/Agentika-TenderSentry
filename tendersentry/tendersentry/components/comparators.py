"""
TenderSentry Deterministic Comparators

Three comparators detect contradictions across PDF documents without using LLM.
Each comparator is deterministic, fast, and explainable. LLMs are used only for
explanation (investigate node); detection is here.

Classes:
    - DateComparator: Find conflicting submission/closing dates
    - AmountComparator: Find financial amount contradictions (line items vs total)
    - RequirementComparator: Find conflicting requirement wording (ISO, mandatory, optional)
    - ContradictionDetector: Orchestrator that runs all three and renumbers findings

Layer: `constants → config_entity → artifact_entity`. No hardcoded values, no LLM.

Import pattern:
    from tendersentry.components.comparators import ContradictionDetector
    from tendersentry.entity.config_entity import ComparatorConfig
    from tendersentry.entity.artifact_entity import DocumentChunk

Never:
    - Call any LLM inside these comparators
    - Hardcode a threshold or keyword that lives in constants
    - Mutate the input chunks list
"""

import re
from datetime import datetime
from typing import Optional
from dateutil.parser import parse as parse_date, ParserError
from pydantic import BaseModel, Field
from tendersentry.entity.config_entity import ComparatorConfig
from tendersentry.entity.artifact_entity import DocumentChunk, RawContradiction
from tendersentry.constants import (
    TYPE_DEADLINE,
    TYPE_AMOUNT,
    TYPE_REQUIREMENT,
    TYPE_SEMANTIC,
    TYPE_INVOICE,
    TYPE_DUPLICATE,
    TYPE_BUDGET_OVERSPEND,
    TYPE_VAT_MISMATCH,
    SEVERITY_HIGH,
    SEVERITY_MEDIUM,
    SEVERITY_LOW,
    AMOUNT_MIN_LINE_ITEMS,
    SEMANTIC_MAX_CHARS_PER_DOC,
    SEMANTIC_MAX_FINDINGS,
    LLM_MODEL_PRIMARY,
    LLM_MAX_RETRIES,
)
from tendersentry.logging.logger import logging


class DateComparator:
    """Extract dates from document chunks and flag contradictions across documents.

    Algorithm:
        1. For each chunk, use dateutil.parser with fuzzy=True to extract dates.
        2. Build a mapping: {filename: [dates_found]}
        3. Compare dates across different documents; flag if diff > tolerance_days.
        4. Extract the sentence containing each date as the excerpt.
    """

    def __init__(self, config: ComparatorConfig):
        """Initialize with comparator config (includes date_tolerance_days).

        Args:
            config: ComparatorConfig with date_tolerance_days, amount_tolerance_pct, etc.
        """
        self.config = config
        logging.info(f"DateComparator initialized with tolerance {config.date_tolerance_days} days")

    def compare(self, chunks: list[DocumentChunk]) -> list[RawContradiction]:
        """Find deadline contradictions across documents.

        Args:
            chunks: List of DocumentChunk objects (each with filename, page_num, text).

        Returns:
            List of RawContradiction objects (empty if no contradictions found).
        """
        logging.info(f"DateComparator.compare: processing {len(chunks)} chunks")
        contradictions = []

        # Extract dates from each chunk
        dates_by_filename = {}  # {filename: [(date_obj, date_string, excerpt, chunk_idx), ...]}
        for chunk in chunks:
            dates_found = self._extract_dates_from_text(chunk.text)
            if dates_found:
                if chunk.filename not in dates_by_filename:
                    dates_by_filename[chunk.filename] = []
                dates_by_filename[chunk.filename].extend(dates_found)

        logging.info(f"DateComparator: extracted dates from {len(dates_by_filename)} unique documents")

        # Compare dates across documents
        filenames = sorted(dates_by_filename.keys())
        for i, filename_a in enumerate(filenames):
            for filename_b in filenames[i + 1 :]:
                # Compare each date from doc_a with each date from doc_b
                for date_a, date_str_a, excerpt_a in dates_by_filename[filename_a]:
                    for date_b, date_str_b, excerpt_b in dates_by_filename[filename_b]:
                        # Check if dates differ by more than tolerance
                        days_diff = abs((date_a - date_b).days)
                        if days_diff > self.config.date_tolerance_days:
                            contradiction = RawContradiction(
                                contradiction_type=TYPE_DEADLINE,
                                doc_a=filename_a,
                                excerpt_a=excerpt_a,
                                doc_b=filename_b,
                                excerpt_b=excerpt_b,
                                severity=SEVERITY_HIGH,
                                finding_id="F-placeholder",  # ContradictionDetector renumbers
                            )
                            contradictions.append(contradiction)
                            logging.warning(
                                f"DateComparator: {filename_a} ({date_str_a}) "
                                f"vs {filename_b} ({date_str_b}) — diff {days_diff} days"
                            )

        # Deduplicate: keep only one contradiction per (doc_a, doc_b) pair
        # (same date pair can appear multiple times if the date repeats in the document)
        seen_pairs = set()
        unique_contradictions = []
        for c in contradictions:
            pair = (c.doc_a, c.doc_b)
            if pair not in seen_pairs:
                seen_pairs.add(pair)
                unique_contradictions.append(c)
        contradictions = unique_contradictions

        logging.info(f"DateComparator: found {len(contradictions)} deadline contradictions")
        return contradictions

    def _extract_dates_from_text(self, text: str) -> list:
        r"""Extract dates from text using regex + dateutil.parser.

        First uses regex to find likely date patterns (DD Month YYYY, DD-MM-YYYY, Month DD YYYY),
        then parses with dateutil. Avoids fuzzy parsing on whole sentences which can pick up
        spurious numbers.

        Returns a list of tuples: (date_obj, date_string, excerpt)
        where date_obj is a datetime object, date_string is the matched string,
        and excerpt is the sentence/phrase containing the date.

        Catches ParserError and logs warning; never raises.
        """
        dates_found = []

        # Regex patterns for common date formats
        # Matches: "20 November 2025", "15 Nov 2025", "15-11-2025", "20/11/2025", "November 20, 2025"
        date_patterns = [
            r'\d{1,2}(?:st|nd|rd|th)?\s+(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4}',
            r'\d{1,2}[-/]\d{1,2}[-/]\d{4}',
            r'(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}',
        ]

        for pattern in date_patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                date_str = match.group()
                try:
                    # Parse the matched date string
                    date_obj = parse_date(date_str, ignoretz=True)

                    # Extract the sentence containing this date
                    start_idx = max(0, match.start() - 100)
                    end_idx = min(len(text), match.end() + 100)
                    excerpt = text[start_idx:end_idx].strip()
                    if len(excerpt) > 200:
                        excerpt = excerpt[:197] + "..."

                    # Reject implausible years (catches "16 October 9001" from "ISO 9001" nearby)
                    if not (1900 <= date_obj.year <= 2099):
                        logging.warning(f"DateComparator: ignoring date with implausible year: '{date_str}'")
                        continue

                    # Only flag dates in a deadline context to reduce false positives
                    surrounding = text[max(0, match.start() - 150):match.end() + 150]
                    if not re.search(
                        r'deadline|submission|closing|due\s+date|last\s+date|submit|received\s+by|no\s+later\s+than',
                        surrounding, re.IGNORECASE
                    ):
                        continue

                    dates_found.append((date_obj, date_str, excerpt))
                except (ParserError, ValueError, TypeError):
                    # Malformed date string; log and skip
                    logging.warning(f"DateComparator: could not parse date string '{date_str}'")
                    continue

        return dates_found


class AmountComparator:
    r"""Extract dollar amounts and flag contradictions between stated totals and line-item sums.

    Algorithm:
        1. Use regex r'\$[\d,]+(?:\.\d{2})?'  to find all dollar amounts.
        2. Identify line-item chunks (multiple $ values) and total chunks (single "Total" or "Contract value").
        3. Compare sum of line items vs stated total; flag if diff > tolerance_pct.
    """

    def __init__(self, config: ComparatorConfig):
        """Initialize with comparator config (includes amount_tolerance_pct).

        Args:
            config: ComparatorConfig with date_tolerance_days, amount_tolerance_pct, etc.
        """
        self.config = config
        logging.info(f"AmountComparator initialized with tolerance {config.amount_tolerance_pct * 100}%")

    def compare(self, chunks: list[DocumentChunk]) -> list[RawContradiction]:
        """Find financial amount contradictions across documents.

        Args:
            chunks: List of DocumentChunk objects.

        Returns:
            List of RawContradiction objects (empty if no contradictions found).
        """
        logging.info(f"AmountComparator.compare: processing {len(chunks)} chunks")
        contradictions = []

        # Extract amounts from each chunk and categorize
        amounts_by_filename = {}  # {filename: [(amount, excerpt, is_total), ...]}

        for chunk in chunks:
            amounts_in_chunk = self._extract_amounts(chunk.text)
            if amounts_in_chunk:
                if chunk.filename not in amounts_by_filename:
                    amounts_by_filename[chunk.filename] = []
                amounts_by_filename[chunk.filename].extend(amounts_in_chunk)

        logging.info(f"AmountComparator: extracted amounts from {len(amounts_by_filename)} unique documents")

        # Find line-item sum vs stated total contradictions using sorted pairs (prevents A,B + B,A duplicates)
        filenames = sorted(amounts_by_filename.keys())
        for i, filename_a in enumerate(filenames):
            for filename_b in filenames[i + 1:]:
                amounts_a = amounts_by_filename[filename_a]
                amounts_b = amounts_by_filename[filename_b]

                # Split by is_total flag
                totals_a = [(amt, exc) for amt, exc, is_total in amounts_a if is_total]
                line_items_a = [(amt, exc) for amt, exc, is_total in amounts_a if not is_total]
                totals_b = [(amt, exc) for amt, exc, is_total in amounts_b if is_total]
                line_items_b = [(amt, exc) for amt, exc, is_total in amounts_b if not is_total]

                # A has line items, B has stated total
                if len(line_items_a) >= AMOUNT_MIN_LINE_ITEMS and totals_b:
                    sum_a = sum(amt for amt, _ in line_items_a)
                    total_b = totals_b[0][0]
                    if total_b > 0:
                        pct_diff = abs(sum_a - total_b) / total_b
                        if pct_diff > self.config.amount_tolerance_pct:
                            excerpt_a = "; ".join([exc for _, exc in line_items_a[:3]])[:200]
                            excerpt_b = totals_b[0][1]
                            contradictions.append(RawContradiction(
                                contradiction_type=TYPE_AMOUNT,
                                doc_a=filename_a,
                                excerpt_a=f"Line items sum to ${sum_a:,.2f} ({excerpt_a})",
                                doc_b=filename_b,
                                excerpt_b=f"Total stated as ${total_b:,.2f} ({excerpt_b})",
                                severity=SEVERITY_HIGH,
                                finding_id="F-placeholder",
                            ))
                            logging.warning(
                                f"AmountComparator: {filename_a} items sum to ${sum_a:,.2f} "
                                f"vs {filename_b} total ${total_b:,.2f} — diff {pct_diff * 100:.1f}%"
                            )

                # B has line items, A has stated total
                if len(line_items_b) >= AMOUNT_MIN_LINE_ITEMS and totals_a:
                    sum_b = sum(amt for amt, _ in line_items_b)
                    total_a = totals_a[0][0]
                    if total_a > 0:
                        pct_diff = abs(sum_b - total_a) / total_a
                        if pct_diff > self.config.amount_tolerance_pct:
                            excerpt_b_str = "; ".join([exc for _, exc in line_items_b[:3]])[:200]
                            excerpt_a_str = totals_a[0][1]
                            contradictions.append(RawContradiction(
                                contradiction_type=TYPE_AMOUNT,
                                doc_a=filename_b,
                                excerpt_a=f"Line items sum to ${sum_b:,.2f} ({excerpt_b_str})",
                                doc_b=filename_a,
                                excerpt_b=f"Total stated as ${total_a:,.2f} ({excerpt_a_str})",
                                severity=SEVERITY_HIGH,
                                finding_id="F-placeholder",
                            ))
                            logging.warning(
                                f"AmountComparator: {filename_b} items sum to ${sum_b:,.2f} "
                                f"vs {filename_a} total ${total_a:,.2f} — diff {pct_diff * 100:.1f}%"
                            )

        logging.info(f"AmountComparator: found {len(contradictions)} amount contradictions")
        return contradictions

    def _extract_amounts(self, text: str) -> list:
        r"""Extract all dollar amounts from text.

        Returns a list of tuples: (amount_float, excerpt, is_total)
        where is_total indicates if this looks like a stated total (vs a line item).

        Uses regex r'\$[\d,]+(?:\.\d{2})?'  to find dollar amounts.
        Gracefully handles malformed currency; logs warnings.
        """
        amounts = []
        pattern = r'\$[\d,]+(?:\.\d{2})?'

        # Find all dollar amounts
        matches = re.finditer(pattern, text)
        for match in matches:
            amount_str = match.group()
            try:
                # Strip $ and commas, convert to float
                amount_float = float(amount_str.replace('$', '').replace(',', ''))

                # Extract the sentence/phrase containing this amount
                start_idx = max(0, match.start() - 100)
                end_idx = min(len(text), match.end() + 100)
                excerpt = text[start_idx:end_idx].strip()
                if len(excerpt) > 200:
                    excerpt = excerpt[:197] + "..."

                # Infer if this is a stated total (look for keywords)
                is_total = bool(re.search(r'(total|contract value|sum|grand total)', text[max(0, match.start() - 50):match.end() + 50], re.IGNORECASE))

                amounts.append((amount_float, excerpt, is_total))
            except ValueError:
                # Malformed amount; log and skip
                logging.warning(f"AmountComparator: could not parse amount '{amount_str}'")
                continue

        return amounts


class RequirementComparator:
    """Match requirement keyword pairs and flag conflicting forms across documents.

    Algorithm:
        1. For each keyword pair in config.requirement_keyword_pairs:
           - Search all chunks for keyword 1
           - Search all OTHER documents' chunks for keyword 2
        2. If found in different documents → contradiction
        3. Extract the sentence containing each keyword
    """

    def __init__(self, config: ComparatorConfig):
        """Initialize with comparator config (includes requirement_keyword_pairs).

        Args:
            config: ComparatorConfig with date_tolerance_days, amount_tolerance_pct, etc.
        """
        self.config = config
        logging.info(f"RequirementComparator initialized with {len(config.requirement_keyword_pairs)} keyword pairs")

    def compare(self, chunks: list[DocumentChunk]) -> list[RawContradiction]:
        """Find requirement wording contradictions across documents.

        Args:
            chunks: List of DocumentChunk objects.

        Returns:
            List of RawContradiction objects (empty if no contradictions found).
        """
        logging.info(f"RequirementComparator.compare: processing {len(chunks)} chunks")
        contradictions = []

        # For each keyword pair, search for form 1 in one doc and form 2 in another
        for keyword_a, keyword_b in self.config.requirement_keyword_pairs:
            # Find all occurrences of keyword_a across documents
            occurrences_a = {}  # {filename: [excerpt, ...]}
            for chunk in chunks:
                if re.search(re.escape(keyword_a), chunk.text, re.IGNORECASE):
                    if chunk.filename not in occurrences_a:
                        occurrences_a[chunk.filename] = []
                    excerpt = self._extract_excerpt_for_keyword(chunk.text, keyword_a)
                    occurrences_a[chunk.filename].append(excerpt)

            # Find all occurrences of keyword_b across documents
            occurrences_b = {}  # {filename: [excerpt, ...]}
            for chunk in chunks:
                if re.search(re.escape(keyword_b), chunk.text, re.IGNORECASE):
                    if chunk.filename not in occurrences_b:
                        occurrences_b[chunk.filename] = []
                    excerpt = self._extract_excerpt_for_keyword(chunk.text, keyword_b)
                    occurrences_b[chunk.filename].append(excerpt)

            # Check for contradictions: keyword_a in doc_a but NOT doc_b, AND keyword_b in doc_b
            # Use sorted pairs to prevent (A,B) and (B,A) both firing
            filenames_a = sorted(occurrences_a.keys())
            for filename_a in filenames_a:
                for filename_b in sorted(occurrences_b.keys()):
                    if filename_a == filename_b:
                        continue
                    # True conflict: keyword_a is in doc_a but doc_b uses keyword_b instead
                    # Skip if doc_b also has keyword_a (both docs agree, not a contradiction)
                    if filename_b in occurrences_a:
                        continue
                    # Skip reversed pair if already covered (prevents A,B + B,A)
                    if filename_b < filename_a and filename_a in occurrences_b:
                        continue

                    excerpt_a = occurrences_a[filename_a][0]
                    excerpt_b = occurrences_b[filename_b][0]

                    contradiction = RawContradiction(
                        contradiction_type=TYPE_REQUIREMENT,
                        doc_a=filename_a,
                        excerpt_a=excerpt_a,
                        doc_b=filename_b,
                        excerpt_b=excerpt_b,
                        severity=SEVERITY_MEDIUM,
                        finding_id="F-placeholder",  # ContradictionDetector renumbers
                    )
                    contradictions.append(contradiction)
                    logging.warning(
                        f"RequirementComparator: '{keyword_a}' in {filename_a} "
                        f"vs '{keyword_b}' in {filename_b}"
                    )

        logging.info(f"RequirementComparator: found {len(contradictions)} requirement contradictions")
        return contradictions

    def _extract_excerpt_for_keyword(self, text: str, keyword: str) -> str:
        """Extract the sentence containing a keyword.

        Splits text by sentence boundaries and returns the sentence with the keyword.
        Returns up to 200 chars.
        """
        sentences = re.split(r'(?<=[.!?])\s+|\n', text)
        for sentence in sentences:
            if re.search(re.escape(keyword), sentence, re.IGNORECASE):
                excerpt = sentence.strip()
                if len(excerpt) > 200:
                    excerpt = excerpt[:197] + "..."
                return excerpt
        return keyword  # Fallback: just return the keyword if we can't find a sentence


class _SemanticFinding(BaseModel):
    """LLM-extracted semantic contradiction between two document excerpts."""
    excerpt_a: str = Field(..., description="Verbatim quote from Document A showing the contradiction")
    excerpt_b: str = Field(..., description="Verbatim quote from Document B showing the contradiction")
    severity: str = Field(..., description="HIGH, MEDIUM, or LOW")
    description: str = Field(..., description="One-sentence summary of the contradiction")


class _SemanticFindings(BaseModel):
    """Wrapper so instructor returns a list."""
    findings: list[_SemanticFinding] = Field(default_factory=list)


class SemanticComparator:
    """LLM-powered comparator that detects factual, scope, and statement contradictions.

    Passes truncated text from each document pair to an LLM via instructor and asks
    it to find contradictions that deterministic comparators cannot catch: conflicting
    eligibility criteria, scope changes, factual inconsistencies, legal clause conflicts.

    Returns at most SEMANTIC_MAX_FINDINGS contradictions per document pair.
    Fails gracefully — returns [] on LLM error so existing comparators are unaffected.
    """

    def __init__(self, config: ComparatorConfig):
        self.config = config
        logging.info("SemanticComparator initialized")

    def compare(self, chunks: list[DocumentChunk]) -> list[RawContradiction]:
        """Find semantic contradictions across unique document pairs.

        Args:
            chunks: List of DocumentChunk objects from all PDFs.

        Returns:
            List of RawContradiction objects with contradiction_type=TYPE_SEMANTIC.
        """
        # Late import to avoid circular dependency at module load time
        from tendersentry.utils.utils import get_instructor_client

        # Build per-document full text (first SEMANTIC_MAX_CHARS_PER_DOC chars)
        docs: dict[str, str] = {}
        for chunk in chunks:
            if chunk.filename not in docs:
                docs[chunk.filename] = ""
            if len(docs[chunk.filename]) < SEMANTIC_MAX_CHARS_PER_DOC:
                docs[chunk.filename] += chunk.text + "\n"

        filenames = sorted(docs.keys())
        if len(filenames) < 2:
            return []

        contradictions: list[RawContradiction] = []

        for i, fn_a in enumerate(filenames):
            for fn_b in filenames[i + 1:]:
                text_a = docs[fn_a][:SEMANTIC_MAX_CHARS_PER_DOC]
                text_b = docs[fn_b][:SEMANTIC_MAX_CHARS_PER_DOC]

                prompt = (
                    f"You are a procurement audit expert. Compare these two tender documents "
                    f"and find factual contradictions, inconsistencies, or conflicting statements "
                    f"that a bidder would need to resolve.\n\n"
                    f"Ignore minor formatting differences. Focus on: conflicting eligibility "
                    f"criteria, scope of work changes, conflicting legal/technical requirements, "
                    f"inconsistent quantities or specifications, conflicting payment terms.\n\n"
                    f"Document A ({fn_a}):\n{text_a}\n\n"
                    f"Document B ({fn_b}):\n{text_b}\n\n"
                    f"Return at most {SEMANTIC_MAX_FINDINGS} contradictions. "
                    f"Only include genuine conflicts, not stylistic differences. "
                    f"Each excerpt must be a verbatim quote from the respective document."
                )

                try:
                    client = get_instructor_client()
                    result: _SemanticFindings = client.chat.completions.create(
                        model=LLM_MODEL_PRIMARY,
                        response_model=_SemanticFindings,
                        messages=[{"role": "user", "content": prompt}],
                        max_retries=LLM_MAX_RETRIES,
                    )
                    severity_map = {"HIGH": SEVERITY_HIGH, "MEDIUM": SEVERITY_MEDIUM, "LOW": SEVERITY_LOW}
                    for f in result.findings[:SEMANTIC_MAX_FINDINGS]:
                        contradictions.append(RawContradiction(
                            contradiction_type=TYPE_SEMANTIC,
                            doc_a=fn_a,
                            excerpt_a=f.excerpt_a[:300],
                            doc_b=fn_b,
                            excerpt_b=f.excerpt_b[:300],
                            severity=severity_map.get(f.severity.upper(), SEVERITY_MEDIUM),
                            finding_id="F-placeholder",
                        ))
                    logging.info(
                        f"SemanticComparator: {fn_a} vs {fn_b} → {len(result.findings)} finding(s)"
                    )
                except Exception as e:
                    logging.error(
                        f"SemanticComparator: LLM call failed for {fn_a} vs {fn_b}: "
                        f"{type(e).__name__}: {e}"
                    )

        logging.info(f"SemanticComparator: found {len(contradictions)} semantic contradictions")
        return contradictions


class InvoiceComparator:
    """Detect invoice-specific issues: duplicates, budget overruns, VAT math errors, unit price discrepancies.

    All detection is deterministic via regex — no LLM calls.
    Only runs when ContradictionDetector.detect() is called with mode='invoice_review'.
    """

    _INV_NUM_RE    = re.compile(r'(?:Invoice|Inv\.?)\s*(?:No\.?|#|Number)?\s*:?\s*([A-Z0-9]{2}[A-Z0-9\-/]{1,18})', re.I)
    _TOTAL_RE      = re.compile(r'(?:Total|Amount\s+Due|Balance\s+Due|Grand\s+Total|Invoice\s+Total)\s*:?\s*\$?\s*([\d,]+(?:\.\d{2})?)', re.I)
    _SUBTOTAL_RE   = re.compile(r'(?:Subtotal|Sub-?total|Net\s+Amount)\s*:?\s*\$?\s*([\d,]+(?:\.\d{2})?)', re.I)
    _TAX_RE        = re.compile(r'(?:VAT|Tax|GST|HST|Sales\s+Tax)\s*(?:\([\d.]+%\))?\s*:?\s*\$?\s*([\d,]+(?:\.\d{2})?)', re.I)
    _BUDGET_RE     = re.compile(r'(?:Budget|Approved\s+Budget|Budget\s+Allocation|Budgeted\s+Amount)\s*:?\s*\$?\s*([\d,]+(?:\.\d{2})?)', re.I)
    _UNIT_PRICE_RE = re.compile(r'(?:Unit\s+Price|Rate|Price\s+Per\s+Unit)\s*:?\s*\$?\s*([\d,]+(?:\.\d{2})?)', re.I)

    def __init__(self, config: ComparatorConfig):
        self.config = config

    @staticmethod
    def _parse(s: str) -> Optional[float]:
        try:
            return float(s.replace(',', ''))
        except (ValueError, AttributeError):
            return None

    def _doc_data(self, chunks: list[DocumentChunk]) -> dict:
        """Combine all chunks per filename and extract invoice fields."""
        by_doc: dict[str, str] = {}
        first_ref: dict[str, Optional[str]] = {}
        for c in chunks:
            by_doc.setdefault(c.filename, '')
            by_doc[c.filename] += c.text + '\n'
            if c.filename not in first_ref:
                first_ref[c.filename] = c.tender_ref
        result = {}
        for fn, text in by_doc.items():
            result[fn] = {
                'inv_nums':    [m.group(1) for m in self._INV_NUM_RE.finditer(text)],
                'totals':      [v for v in (self._parse(m.group(1)) for m in self._TOTAL_RE.finditer(text)) if v],
                'subtotals':   [v for v in (self._parse(m.group(1)) for m in self._SUBTOTAL_RE.finditer(text)) if v],
                'taxes':       [v for v in (self._parse(m.group(1)) for m in self._TAX_RE.finditer(text)) if v],
                'budgets':     [v for v in (self._parse(m.group(1)) for m in self._BUDGET_RE.finditer(text)) if v],
                'unit_prices': [v for v in (self._parse(m.group(1)) for m in self._UNIT_PRICE_RE.finditer(text)) if v],
                'tender_ref':  first_ref.get(fn),
            }
        return result

    def compare(self, chunks: list[DocumentChunk]) -> list[RawContradiction]:
        """Find invoice contradictions: duplicates, budget overruns, VAT errors, price discrepancies."""
        data = self._doc_data(chunks)
        docs = list(data.keys())
        if not docs:
            return []

        contradictions: list[RawContradiction] = []
        seen: set = set()
        tol = self.config.amount_tolerance_pct

        # 1. VAT/tax math check — within each document
        for fn, d in data.items():
            if d['subtotals'] and d['taxes'] and d['totals']:
                sub, tax, stated = d['subtotals'][0], d['taxes'][0], d['totals'][0]
                if stated > 0 and abs(sub + tax - stated) / stated > tol:
                    key = (TYPE_VAT_MISMATCH, fn, fn)
                    if key not in seen:
                        seen.add(key)
                        contradictions.append(RawContradiction(
                            finding_id='F-placeholder',
                            contradiction_type=TYPE_VAT_MISMATCH,
                            doc_a=fn, excerpt_a=f'Subtotal ${sub:,.2f} + Tax ${tax:,.2f} = ${sub+tax:,.2f}',
                            doc_b=fn, excerpt_b=f'Stated Total: ${stated:,.2f} (gap: ${abs(sub+tax-stated):,.2f})',
                            severity=SEVERITY_HIGH,
                        ))

        # Cross-document checks
        for i in range(len(docs)):
            for j in range(i + 1, len(docs)):
                a, b = docs[i], docs[j]
                da, db = data[a], data[b]

                # 2. Duplicate invoice number
                for inv in sorted(set(da['inv_nums']) & set(db['inv_nums'])):
                    key = (TYPE_DUPLICATE, a, b, inv)
                    if key not in seen:
                        seen.add(key)
                        contradictions.append(RawContradiction(
                            finding_id='F-placeholder',
                            contradiction_type=TYPE_DUPLICATE,
                            doc_a=a, excerpt_a=f'Invoice #{inv} in {a}',
                            doc_b=b, excerpt_b=f'Invoice #{inv} also in {b} — possible duplicate',
                            severity=SEVERITY_HIGH,
                        ))

                # 3. Identical total amounts across docs (duplicate by amount)
                for amt_a in da['totals']:
                    for amt_b in db['totals']:
                        if amt_a > 100 and abs(amt_a - amt_b) / amt_a < 0.001:
                            key = ('dup_amount', a, b, round(amt_a))
                            if key not in seen:
                                seen.add(key)
                                contradictions.append(RawContradiction(
                                    finding_id='F-placeholder',
                                    contradiction_type=TYPE_DUPLICATE,
                                    doc_a=a, excerpt_a=f'Total: ${amt_a:,.2f}',
                                    doc_b=b, excerpt_b=f'Total: ${amt_b:,.2f} — identical amounts, verify not duplicate',
                                    severity=SEVERITY_MEDIUM,
                                ))

                # 4. Budget vs actuals — one doc has budget, other has invoice exceeding it
                for budget_doc, budget_d, inv_doc, inv_d in [(a, da, b, db), (b, db, a, da)]:
                    if budget_d['budgets'] and inv_d['totals']:
                        budget_amt, inv_amt = budget_d['budgets'][0], inv_d['totals'][0]
                        if budget_amt > 0 and (inv_amt - budget_amt) / budget_amt > tol:
                            key = (TYPE_BUDGET_OVERSPEND, budget_doc, inv_doc)
                            if key not in seen:
                                seen.add(key)
                                over_pct = (inv_amt - budget_amt) / budget_amt * 100
                                contradictions.append(RawContradiction(
                                    finding_id='F-placeholder',
                                    contradiction_type=TYPE_BUDGET_OVERSPEND,
                                    doc_a=budget_doc, excerpt_a=f'Budget: ${budget_amt:,.2f}',
                                    doc_b=inv_doc, excerpt_b=f'Invoice Total: ${inv_amt:,.2f} (+{over_pct:.1f}% over budget)',
                                    severity=SEVERITY_HIGH if over_pct > 10 else SEVERITY_MEDIUM,
                                ))

                # 5. Unit price discrepancy across documents
                if da['unit_prices'] and db['unit_prices']:
                    pa, pb = da['unit_prices'][0], db['unit_prices'][0]
                    if pa > 0 and pb > 0:
                        diff = abs(pa - pb) / max(pa, pb)
                        if diff > tol:
                            key = (TYPE_INVOICE, a, b)
                            if key not in seen:
                                seen.add(key)
                                contradictions.append(RawContradiction(
                                    finding_id='F-placeholder',
                                    contradiction_type=TYPE_INVOICE,
                                    doc_a=a, excerpt_a=f'Unit Price: ${pa:,.2f}',
                                    doc_b=b, excerpt_b=f'Unit Price: ${pb:,.2f} ({diff*100:.1f}% difference)',
                                    severity=SEVERITY_HIGH if diff > 0.05 else SEVERITY_MEDIUM,
                                ))

        logging.info(f'InvoiceComparator.compare: {len(contradictions)} invoice findings')
        return contradictions


class ContradictionDetector:
    """Orchestrator that runs all three comparators and combines results.

    Renumbers finding_ids sequentially (F-001, F-002, F-003, ...) across all results.
    """

    def __init__(self, config: ComparatorConfig):
        """Initialize all three comparators with shared config.

        Args:
            config: ComparatorConfig instance.
        """
        self.config = config
        self.date_cmp = DateComparator(config)
        self.amount_cmp = AmountComparator(config)
        self.req_cmp = RequirementComparator(config)
        self.semantic_cmp = SemanticComparator(config)
        logging.info("ContradictionDetector initialized")

    def detect(self, chunks: list[DocumentChunk], mode: str = "standard") -> list[RawContradiction]:
        """Run comparators and return combined, renumbered results.

        Args:
            chunks: List of DocumentChunk objects (from extract node).
            mode: Analysis mode — 'invoice_review' also runs InvoiceComparator.

        Returns:
            List of RawContradiction objects, renumbered F-001, F-002, ...
        """
        logging.info(f"ContradictionDetector.detect: running comparators on {len(chunks)} chunks, mode={mode}")

        # Collect results from all comparators (deterministic first, semantic last)
        results = []
        results.extend(self.date_cmp.compare(chunks))
        results.extend(self.amount_cmp.compare(chunks))
        results.extend(self.req_cmp.compare(chunks))
        results.extend(self.semantic_cmp.compare(chunks))
        if mode == "invoice_review":
            results.extend(InvoiceComparator(self.config).compare(chunks))

        # Deduplicate: types that can have multiple findings per doc pair use excerpt as tiebreaker
        _multi_per_pair = {TYPE_SEMANTIC, TYPE_DUPLICATE, TYPE_INVOICE, TYPE_BUDGET_OVERSPEND, TYPE_VAT_MISMATCH}
        seen: set = set()
        unique = []
        for r in results:
            key = (r.contradiction_type, r.doc_a, r.doc_b, r.excerpt_a[:60]) \
                if r.contradiction_type in _multi_per_pair \
                else (r.contradiction_type, r.doc_a, r.doc_b)
            if key not in seen:
                seen.add(key)
                unique.append(r)
        results = unique

        # Renumber finding_ids sequentially
        for i, r in enumerate(results, 1):
            r.finding_id = f"F-{i:03d}"

        logging.info(f"ContradictionDetector: detected {len(results)} total contradictions")
        return results


# Self-check: deterministic test with known contradictions
if __name__ == "__main__":
    logging.info("Running comparators self-check...")

    # Test chunks (mimic the 3 planted contradictions)
    test_chunks = [
        DocumentChunk(
            filename="main_notice.pdf",
            page_num=1,
            text="Submission by 20 November 2025. ISO 9001:2015 mandatory. Contract value: $820,000.",
        ),
        DocumentChunk(
            filename="schedule_a.pdf",
            page_num=1,
            text="Closing date 15 November 2025. ISO 9001 or equivalent accepted.",
        ),
        DocumentChunk(
            filename="boq.pdf",
            page_num=1,
            text="Item 1: $500,000. Item 2: $347,000. Total line items: $847,000.",
        ),
    ]

    # Create config with constants
    from tendersentry.constants import DATE_TOLERANCE_DAYS, AMOUNT_TOLERANCE_PCT, REQUIREMENT_KEYWORD_PAIRS

    config = ComparatorConfig(
        date_tolerance_days=DATE_TOLERANCE_DAYS,
        amount_tolerance_pct=AMOUNT_TOLERANCE_PCT,
        requirement_keyword_pairs=REQUIREMENT_KEYWORD_PAIRS,
    )

    # Run detector
    detector = ContradictionDetector(config)
    contradictions = detector.detect(test_chunks)

    # Print results
    print(f"\nFound {len(contradictions)} contradictions:")
    for c in contradictions:
        print(f"  {c.finding_id}: {c.contradiction_type} ({c.severity})")
        print(f"    {c.doc_a}: {c.excerpt_a[:80]}")
        print(f"    {c.doc_b}: {c.excerpt_b[:80]}")

    # Assert at least 2 contradictions (deadline + amount or requirement)
    assert len(contradictions) >= 2, f"Expected at least 2 contradictions, got {len(contradictions)}"
    print("\nSelf-check passed.")
