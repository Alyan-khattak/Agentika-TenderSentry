"""
generate_docs.py — Synthetic PDF generation for TenderSentry testing.

Generates three PDFs with planted contradictions:
1. Deadline: 20 Nov vs 15 Nov
2. ISO Requirement: mandatory vs equivalent
3. Contract amount: $847,000 (line items) vs $820,000 (stated total)

Run this script to populate artifacts/ with test documents for manual
and automated testing. The contradictions are deterministic and trigger
the DateComparator, RequirementComparator, and AmountComparator.
"""

import os
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak

from tendersentry.constants import (
    PDF_OUTPUT_DIR,
    PDF_MAIN_NOTICE,
    PDF_SCHEDULE_A,
    PDF_BOQ,
)


def _setup_styles():
    """Return styled Paragraph objects for headings and body text."""
    styles = getSampleStyleSheet()

    # Title style
    title_style = ParagraphStyle(
        "CustomTitle",
        parent=styles["Heading1"],
        fontSize=14,
        textColor="black",
        spaceAfter=12,
        alignment=0,  # left align
    )

    # Heading style
    heading_style = ParagraphStyle(
        "CustomHeading",
        parent=styles["Heading2"],
        fontSize=11,
        textColor="black",
        spaceAfter=8,
        alignment=0,
    )

    # Body style
    body_style = ParagraphStyle(
        "CustomBody",
        parent=styles["Normal"],
        fontSize=10,
        textColor="black",
        spaceAfter=6,
        alignment=0,
    )

    return title_style, heading_style, body_style


def generate_main_notice():
    """
    Generate main_notice.pdf — Tender notice with:
    - Deadline: 20 November 2025 (CONTRADICTION #1 vs schedule_a.pdf: 15 Nov)
    - Contract Value: $820,000 (CONTRADICTION #3 vs boq.pdf: $847,000)
    - ISO Requirement: mandatory (CONTRADICTION #2 vs schedule_a.pdf: or equivalent)
    """
    output_path = os.path.join(PDF_OUTPUT_DIR, PDF_MAIN_NOTICE)
    doc = SimpleDocTemplate(output_path, pagesize=A4, topMargin=0.75*inch, bottomMargin=0.75*inch)

    story = []
    title_style, heading_style, body_style = _setup_styles()

    # Page 1 — Tender Notice
    story.append(Paragraph("TENDER NOTICE — REF: PKG-2025-047", title_style))
    story.append(Spacer(1, 0.2*inch))

    story.append(Paragraph("GOVERNMENT OF PAKISTAN", heading_style))
    story.append(Paragraph("MINISTRY OF PUBLIC WORKS", heading_style))
    story.append(Spacer(1, 0.1*inch))

    story.append(Paragraph("INVITATION TO BID", heading_style))
    story.append(Spacer(1, 0.1*inch))

    story.append(Paragraph("Project: Construction of Regional Water Treatment Facility", body_style))
    story.append(Paragraph("Location: Lahore, Punjab Province", body_style))
    story.append(Paragraph("Tender Reference: PKG-2025-047", body_style))
    story.append(Spacer(1, 0.1*inch))

    story.append(Paragraph(
        "This notice invites sealed bids from qualified contractors for the "
        "construction of a regional water treatment facility.",
        body_style
    ))
    story.append(Spacer(1, 0.1*inch))

    # CRITICAL: Deadline must be "20 November 2025" (comparator uses dateutil.parser on this)
    story.append(Paragraph("Submission Deadline: 20 November 2025, 17:00 PKT", body_style))
    story.append(Spacer(1, 0.1*inch))

    story.append(Paragraph(
        "All bids must be submitted to the Procurement Office, Room 201, "
        "Ministry Building, Islamabad.",
        body_style
    ))
    story.append(Spacer(1, 0.1*inch))

    # CRITICAL: Contract Value must be "$820,000" (AmountComparator looks for $NNN,NNN)
    story.append(Paragraph("Contract Value: $820,000", body_style))
    story.append(Spacer(1, 0.1*inch))

    story.append(Paragraph("Bids received after the deadline will not be considered.", body_style))

    story.append(PageBreak())

    # Page 2 — Technical Requirements
    story.append(Paragraph("TECHNICAL REQUIREMENTS", heading_style))
    story.append(Spacer(1, 0.1*inch))

    story.append(Paragraph("1. Quality Management System", body_style))
    # CRITICAL: Must contain "ISO 9001:2015 certification is mandatory"
    # (RequirementComparator looks for ("ISO 9001:2015", "mandatory"))
    story.append(Paragraph(
        "Bidders must hold current ISO 9001:2015 certification is mandatory. "
        "Evidence of certification must be submitted with the bid.",
        body_style
    ))
    story.append(Spacer(1, 0.1*inch))

    story.append(Paragraph("2. Experience Requirements", body_style))
    story.append(Paragraph(
        "Minimum 5 years experience in water infrastructure projects. "
        "At least 3 completed projects of similar scope.",
        body_style
    ))
    story.append(Spacer(1, 0.1*inch))

    story.append(Paragraph("3. Financial Requirements", body_style))
    story.append(Paragraph(
        "Minimum annual turnover of $2,000,000 for the past 3 years. "
        "Bank guarantee of 5% of bid value required.",
        body_style
    ))

    story.append(PageBreak())

    # Page 3 — Evaluation Criteria
    story.append(Paragraph("EVALUATION CRITERIA", heading_style))
    story.append(Spacer(1, 0.1*inch))

    story.append(Paragraph(
        "Bids will be evaluated on the following criteria:",
        body_style
    ))
    story.append(Paragraph("- Technical compliance: 40%", body_style))
    story.append(Paragraph("- Financial proposal: 40%", body_style))
    story.append(Paragraph("- Past experience: 20%", body_style))
    story.append(Spacer(1, 0.1*inch))

    story.append(Paragraph("Incomplete bids will be rejected without evaluation.", body_style))

    doc.build(story)
    print(f"✓ Generated {output_path}")


def generate_schedule_a():
    """
    Generate schedule_a.pdf — Schedule A with:
    - Deadline: 15 November 2025 (CONTRADICTION #1 vs main_notice.pdf: 20 Nov)
    - ISO Requirement: or equivalent (CONTRADICTION #2 vs main_notice.pdf: mandatory)
    """
    output_path = os.path.join(PDF_OUTPUT_DIR, PDF_SCHEDULE_A)
    doc = SimpleDocTemplate(output_path, pagesize=A4, topMargin=0.75*inch, bottomMargin=0.75*inch)

    story = []
    title_style, heading_style, body_style = _setup_styles()

    # Page 1 — Schedule A: Bid Conditions
    story.append(Paragraph("SCHEDULE A — BID CONDITIONS", title_style))
    story.append(Paragraph("Tender Reference: PKG-2025-047", body_style))
    story.append(Spacer(1, 0.1*inch))

    story.append(Paragraph("IMPORTANT DATES", heading_style))
    story.append(Spacer(1, 0.05*inch))

    # CRITICAL: Deadline must be "15 November 2025" (different from main_notice.pdf)
    story.append(Paragraph("Closing Date: 15 November 2025", body_style))
    story.append(Spacer(1, 0.1*inch))

    story.append(Paragraph(
        "Bids must arrive at the procurement office no later than "
        "15 November 2025 at 17:00 PKT.",
        body_style
    ))
    story.append(Spacer(1, 0.1*inch))

    story.append(Paragraph("Late submissions will be automatically disqualified.", body_style))
    story.append(Spacer(1, 0.2*inch))

    story.append(Paragraph("CERTIFICATION REQUIREMENTS", heading_style))
    story.append(Spacer(1, 0.05*inch))

    # CRITICAL: Must contain "ISO 9001 or equivalent" (different from main_notice.pdf: mandatory)
    # (RequirementComparator looks for ("ISO 9001:2015", "or equivalent") pair)
    story.append(Paragraph(
        "ISO 9001 or equivalent certification is accepted. "
        "Third-party quality management certification equivalent to "
        "ISO 9001 standards will also be considered.",
        body_style
    ))

    story.append(PageBreak())

    # Page 2 — Special Conditions
    story.append(Paragraph("SPECIAL CONDITIONS", heading_style))
    story.append(Spacer(1, 0.1*inch))

    story.append(Paragraph(
        "1. All prices must be submitted in Pakistani Rupees (PKR) "
        "or US Dollars (USD).",
        body_style
    ))
    story.append(Spacer(1, 0.1*inch))

    story.append(Paragraph(
        "2. The contracting authority reserves the right to reject "
        "any or all bids without explanation.",
        body_style
    ))
    story.append(Spacer(1, 0.1*inch))

    story.append(Paragraph(
        "3. Bid validity period: 90 days from submission date.",
        body_style
    ))

    doc.build(story)
    print(f"✓ Generated {output_path}")


def generate_boq():
    """
    Generate boq.pdf — Bill of Quantities with:
    - Line items totaling $847,000 (CONTRADICTION #3 vs main_notice.pdf: $820,000)
    """
    output_path = os.path.join(PDF_OUTPUT_DIR, PDF_BOQ)
    doc = SimpleDocTemplate(output_path, pagesize=A4, topMargin=0.75*inch, bottomMargin=0.75*inch)

    story = []
    title_style, heading_style, body_style = _setup_styles()

    # Page 1 — Bill of Quantities
    story.append(Paragraph("BILL OF QUANTITIES", title_style))
    story.append(Paragraph("Tender Reference: PKG-2025-047", body_style))
    story.append(Spacer(1, 0.2*inch))

    story.append(Paragraph("SECTION 1: CIVIL WORKS", heading_style))
    story.append(Spacer(1, 0.1*inch))

    # CRITICAL: Each line item must be "$NNN,NNN" format for AmountComparator regex
    story.append(Paragraph("Item 1: Site Preparation and Earthworks         $120,000", body_style))
    story.append(Paragraph("Item 2: Foundation and Structural Works         $180,000", body_style))
    story.append(Paragraph("Item 3: Water Treatment Plant Equipment         $250,000", body_style))
    story.append(Paragraph("Item 4: Pipe Network and Distribution           $150,000", body_style))
    story.append(Paragraph("Item 5: Electrical and Control Systems           $85,000", body_style))
    story.append(Paragraph("Item 6: Testing and Commissioning               $32,000", body_style))
    story.append(Spacer(1, 0.1*inch))

    # Section subtotal (sum of items above)
    story.append(Paragraph("Section 1 Subtotal:                            $817,000", body_style))

    story.append(PageBreak())

    # Page 2 — Cost Summary
    story.append(Paragraph("COST SUMMARY", heading_style))
    story.append(Spacer(1, 0.1*inch))

    story.append(Paragraph("Section 1 Civil Works Subtotal:  $817,000", body_style))
    story.append(Paragraph("Contingency (3.6%):               $30,000", body_style))
    story.append(Spacer(1, 0.1*inch))

    # CRITICAL: Total line items must be "$847,000" (different from contract value $820,000)
    # AmountComparator will flag this as a contradiction (3.3% difference > 1% tolerance)
    story.append(Paragraph("TOTAL LINE ITEMS:                $847,000", body_style))
    story.append(Spacer(1, 0.2*inch))

    story.append(Paragraph("Notes: All amounts are in US Dollars (USD).", body_style))
    story.append(Paragraph("Prices are fixed for the duration of the contract.", body_style))

    doc.build(story)
    print(f"✓ Generated {output_path}")


if __name__ == "__main__":
    # Ensure artifacts directory exists
    os.makedirs(PDF_OUTPUT_DIR, exist_ok=True)

    print(f"Generating test PDFs in {PDF_OUTPUT_DIR}/...")
    generate_main_notice()
    generate_schedule_a()
    generate_boq()
    print("Done. Generated 3 PDFs with planted contradictions:")
    print("  1. Deadline: 20 Nov (main_notice) vs 15 Nov (schedule_a)")
    print("  2. ISO Requirement: mandatory (main_notice) vs or equivalent (schedule_a)")
    print("  3. Amount: $847,000 (boq line items) vs $820,000 (main_notice contract value)")
