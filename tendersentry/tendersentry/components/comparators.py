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
from dateutil.parser import parse as parse_date, ParserError
from tendersentry.entity.config_entity import ComparatorConfig
from tendersentry.entity.artifact_entity import DocumentChunk, RawContradiction
from tendersentry.constants import (
    TYPE_DEADLINE,
    TYPE_AMOUNT,
    TYPE_REQUIREMENT,
    SEVERITY_HIGH,
    SEVERITY_MEDIUM,
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
                if line_items_a and totals_b:
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
                if line_items_b and totals_a:
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

            # Check for contradictions: form 1 in one doc, form 2 in a different doc
            for filename_a in occurrences_a:
                for filename_b in occurrences_b:
                    if filename_a != filename_b:
                        # Found contradiction: form 1 in doc_a, form 2 in doc_b
                        excerpt_a = occurrences_a[filename_a][0]  # First occurrence
                        excerpt_b = occurrences_b[filename_b][0]  # First occurrence

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
        logging.info("ContradictionDetector initialized")

    def detect(self, chunks: list[DocumentChunk]) -> list[RawContradiction]:
        """Run all three comparators and return combined, renumbered results.

        Args:
            chunks: List of DocumentChunk objects (from extract node).

        Returns:
            List of RawContradiction objects, sorted by type and renumbered F-001, F-002, ...
        """
        logging.info(f"ContradictionDetector.detect: running all comparators on {len(chunks)} chunks")

        # Collect results from all three comparators
        results = []
        results.extend(self.date_cmp.compare(chunks))
        results.extend(self.amount_cmp.compare(chunks))
        results.extend(self.req_cmp.compare(chunks))

        # Deduplicate: keep first contradiction per (type, doc_a, doc_b)
        # Multiple keyword pairs can fire for the same document pair
        seen: set = set()
        unique = []
        for r in results:
            key = (r.contradiction_type, r.doc_a, r.doc_b)
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
