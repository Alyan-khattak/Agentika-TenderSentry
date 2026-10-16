"""
PDFExtractor: extracts text from PDF files using PyMuPDF (fitz).

The extract component reads one or more PDF documents, extracts text page by page,
and returns a list of DocumentChunk objects ready for downstream processing
(contradiction detection, LLM analysis, etc.).

Layer: imports from constants, entity, exception, logging only.

Example:
    from tendersentry.entity.config_entity import ExtractorConfig
    from tendersentry.components.extractor import PDFExtractor

    config = ExtractorConfig(
        pdf_paths=["/path/to/doc1.pdf", "/path/to/doc2.pdf"],
        artifacts_dir="artifacts"
    )
    extractor = PDFExtractor(config)
    artifact = extractor.extract()  # Returns ExtractionArtifact
    print(f"Extracted {artifact.total_pages} pages")
"""

import os
import sys
import re
import fitz  # PyMuPDF

from tendersentry.entity.config_entity import ExtractorConfig
from tendersentry.entity.artifact_entity import DocumentChunk, ExtractionArtifact
from tendersentry.exception.exception import TenderSentryException
from tendersentry.logging.logger import logging
from tendersentry.constants import TENDER_REF_RE


class PDFExtractor:
    """Extracts text content from PDF files page by page.

    Attributes:
        config: ExtractorConfig instance with pdf_paths and artifacts_dir.
    """

    def __init__(self, config: ExtractorConfig):
        """Initialize PDFExtractor with configuration.

        Args:
            config: ExtractorConfig instance specifying PDF paths and output directory.
        """
        self.config = config

    def extract(self) -> ExtractionArtifact:
        """Extract text from all PDFs in config.pdf_paths.

        For each PDF:
          1. Open with fitz.open(path)
          2. Iterate pages (0-indexed)
          3. Extract text with page.get_text()
          4. Skip empty pages after strip
          5. Create DocumentChunk with 1-indexed page_num

        Returns:
            ExtractionArtifact: object with chunks (list of DocumentChunk) and total_pages.

        Raises:
            TenderSentryException: if fitz.open() fails or other errors occur.
        """
        logging.info(
            f"Extractor started: {len(self.config.pdf_paths)} PDF(s) to process"
        )

        all_chunks = []

        try:
            for pdf_path in self.config.pdf_paths:
                # Get base filename for DocumentChunk
                filename = os.path.basename(pdf_path)

                # Open PDF; fitz.open() raises if file not found or corrupted
                try:
                    pdf_doc = fitz.open(pdf_path)
                except Exception as e:
                    raise TenderSentryException(
                        f"Failed to open PDF '{pdf_path}': {str(e)}", sys
                    )

                # Get page count before iteration
                page_count = len(pdf_doc)

                # Extract tender reference from page 1 (if it exists)
                tender_ref = None
                if page_count > 0:
                    try:
                        page1_text = pdf_doc[0].get_text()
                        match = re.search(TENDER_REF_RE, page1_text, re.IGNORECASE)
                        tender_ref = match.group(1).upper() if match else None
                    except Exception as e:
                        logging.warning(f"Failed to extract tender_ref from {filename}: {str(e)}")

                # Iterate pages: fitz uses 0-indexed pages internally
                for page_idx in range(page_count):
                    page = pdf_doc[page_idx]
                    text = page.get_text()

                    # Skip empty pages
                    text_stripped = text.strip()
                    if not text_stripped:
                        logging.debug(
                            f"Skipped empty page {page_idx + 1} in {filename}"
                        )
                        continue

                    # Create DocumentChunk: page_num is 1-indexed for users
                    chunk = DocumentChunk(
                        filename=filename,
                        page_num=page_idx + 1,  # Convert to 1-indexed
                        text=text_stripped,
                        tender_ref=tender_ref,  # Set tender_ref on all chunks from this document
                    )
                    all_chunks.append(chunk)

                pdf_doc.close()
                logging.info(f"Extracted {page_count} pages from {filename}, tender_ref={tender_ref}")

            # Build and return artifact
            artifact = ExtractionArtifact(
                chunks=all_chunks,
                total_pages=len(all_chunks),
            )
            logging.info(
                f"Extractor completed: {artifact.total_pages} total pages extracted"
            )
            return artifact

        except TenderSentryException:
            # Re-raise our own exceptions
            raise
        except Exception as e:
            # Catch any other unexpected errors and wrap them
            raise TenderSentryException(
                f"Unexpected error during PDF extraction: {str(e)}", sys
            )


if __name__ == "__main__":
    """Self-check: test basic instantiation and error handling."""
    import tempfile

    # Test 1: Instantiation with empty list (should succeed)
    config = ExtractorConfig(pdf_paths=[], artifacts_dir="artifacts")
    extractor = PDFExtractor(config)
    print("✓ PDFExtractor instantiation OK")

    # Test 2: Extract from empty list (should return empty artifact)
    result = extractor.extract()
    assert result.total_pages == 0, "Expected 0 pages from empty list"
    assert len(result.chunks) == 0, "Expected 0 chunks"
    print("✓ Extract from empty list OK")

    # Test 3: Extract from nonexistent file (should raise TenderSentryException)
    config_bad = ExtractorConfig(
        pdf_paths=["/nonexistent/file.pdf"], artifacts_dir="artifacts"
    )
    extractor_bad = PDFExtractor(config_bad)
    try:
        extractor_bad.extract()
        print("✗ Should have raised TenderSentryException for missing file")
        sys.exit(1)
    except TenderSentryException as e:
        print(f"✓ Correctly raised TenderSentryException: {e}")

    print("\nAll self-checks passed!")
