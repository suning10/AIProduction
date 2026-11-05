# /// script
# requires-python = ">=3.10"
# dependencies = ["reportlab>=4", "rich"]
# ///
# pyright: reportMissingModuleSource=false
"""Generate two fictional SOP PDFs that contradict each other, for conflict retrieval tests.

Both describe sample holding times for the same (fictional) Riverbend Environmental
Laboratory, but disagree on nitrate/metals holding times, storage temperature,
control-limit width and who approves deviations. Neither document says it
supersedes the other, so a correct RAG answer must surface both and flag the
conflict. The values live mostly in tables, where docling and pypdf differ.

The matching test queries (``"match": "all"``) are in ``parser_eval_queries.jsonl``.

reportlab is declared inline (PEP 723), so it isn't a project dependency:
    uv run scripts/make_conflict_pdfs.py                        # -> /Users/mw/Documents/AI/PDFS/conflict_test
    uv run scripts/make_conflict_pdfs.py --out-dir /tmp/conflict
"""

import argparse
from pathlib import Path
from typing import (
    List,
    Tuple,
)

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import (
    Flowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from rich.console import Console

DEFAULT_OUT_DIR = "/Users/mw/Documents/AI/PDFS/conflict_test"

Section = Tuple[str, List[str], List[List[str]]]  # heading, paragraphs, table rows (first row = header)

COMMON_SCOPE = (
    "This procedure applies to all aqueous samples received by the Riverbend Environmental Laboratory "
    "for inorganic and metals analysis, including drinking water, surface water and wastewater. "
    "Samples that are analyzed outside the holding times defined here must be qualified in the final report."
)

DOCS: dict[str, dict] = {
    "riverbend-sop-qa-101-rev-3-sample-holding-times": {
        "title": "Riverbend Environmental Laboratory - SOP QA-101 Rev. 3",
        "subtitle": "Sample Preservation and Holding Times. Effective date: March 1, 2021. Owner: Quality Assurance Unit.",
        "sections": [
            ("1. Scope", [COMMON_SCOPE], []),
            (
                "2. Sample Storage",
                [
                    "Upon receipt, all samples must be stored in the walk-in cooler at or below 6 degrees Celsius "
                    "and must not be frozen. Cooler temperature is recorded twice daily in the temperature log.",
                    "Samples received above 6 degrees Celsius are accepted only if they were collected within the "
                    "previous 2 hours and show evidence of cooling (ice present in the shipping container).",
                ],
                [],
            ),
            (
                "3. Holding Times",
                [
                    "Holding time is measured from the date and time of collection to the start of analysis. "
                    "The maximum holding times in Table 1 are mandatory."
                ],
                [
                    ["Analyte", "Container", "Preservation", "Maximum holding time"],
                    ["Nitrate (as N)", "Plastic, 250 mL", "Cool to 6 C or below", "48 hours"],
                    ["Nitrite (as N)", "Plastic, 250 mL", "Cool to 6 C or below", "48 hours"],
                    ["Total metals", "Plastic, 500 mL", "HNO3 to pH below 2", "6 months"],
                    ["Mercury", "Glass, 250 mL", "HNO3 to pH below 2", "28 days"],
                ],
            ),
            (
                "4. Quality Control",
                [
                    "Laboratory control samples are evaluated against control limits set at the mean plus or minus "
                    "3 standard deviations of the previous 20 results.",
                ],
                [],
            ),
            (
                "5. Deviations",
                [
                    "Any deviation from the holding times or storage conditions in this SOP must be approved in writing "
                    "by the Quality Assurance Manager before the sample is analyzed. Approved deviations are recorded "
                    "in the LIMS deviation log.",
                ],
                [],
            ),
        ],
    },
    "riverbend-field-guide-fg-07-sample-holding-times": {
        "title": "Riverbend Environmental Laboratory - Field Operations Guide FG-07",
        "subtitle": "Sample Handling and Holding Times. Effective date: August 15, 2024. Owner: Field Operations Unit.",
        "sections": [
            ("1. Scope", [COMMON_SCOPE], []),
            (
                "2. Sample Storage",
                [
                    "Samples must be kept at or below 10 degrees Celsius from collection until analysis. "
                    "Freezing is permitted for nutrient samples when analysis cannot start within 24 hours.",
                    "Samples received above 10 degrees Celsius are rejected unless the field team lead documents "
                    "the reason on the chain-of-custody form.",
                ],
                [],
            ),
            (
                "3. Holding Times",
                [
                    "Holding time starts when the sample arrives at the laboratory. Use the limits in Table 1 "
                    "when scheduling analyses."
                ],
                [
                    ["Analyte", "Container", "Preservation", "Maximum holding time"],
                    ["Nitrate (as N)", "Plastic, 250 mL", "Cool to 10 C or below", "7 days"],
                    ["Nitrite (as N)", "Plastic, 250 mL", "Cool to 10 C or below", "48 hours"],
                    ["Total metals", "Plastic, 500 mL", "HNO3 to pH below 2", "28 days"],
                    ["Mercury", "Glass, 250 mL", "HNO3 to pH below 2", "28 days"],
                ],
            ),
            (
                "4. Quality Control",
                [
                    "Laboratory control samples are evaluated against control limits set at the mean plus or minus "
                    "2 standard deviations of the previous 30 results.",
                ],
                [],
            ),
            (
                "5. Deviations",
                [
                    "Deviations from holding times or storage temperature may be approved verbally by the Laboratory "
                    "Director and documented on the chain-of-custody form within 5 business days.",
                ],
                [],
            ),
        ],
    },
}

console = Console()


def build_pdf(path: Path, title: str, subtitle: str, sections: List[Section]) -> None:
    """Render one document (headings, paragraphs, tables) to ``path``."""
    styles = getSampleStyleSheet()
    story: List[Flowable] = [Paragraph(title, styles["Title"]), Paragraph(subtitle, styles["Italic"]), Spacer(1, 12)]
    for heading, paragraphs, rows in sections:
        story.append(Paragraph(heading, styles["Heading2"]))
        story.extend(Paragraph(p, styles["BodyText"]) for p in paragraphs)
        if rows:
            story.append(Spacer(1, 6))
            table = Table(rows, hAlign="LEFT")
            table.setStyle(
                TableStyle(
                    [
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ]
                )
            )
            story.append(table)
            story.append(Paragraph("Table 1. Maximum holding times.", styles["Italic"]))
        story.append(Spacer(1, 8))
    SimpleDocTemplate(str(path), pagesize=letter, title=title).build(story)


def main() -> None:
    """Write both conflicting PDFs."""
    parser = argparse.ArgumentParser(description="Generate two conflicting SOP PDFs for RAG tests.")
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR, help=f"Output folder (default: {DEFAULT_OUT_DIR})")
    out_dir = Path(parser.parse_args().out_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    for stem, doc in DOCS.items():
        path = out_dir / f"{stem}.pdf"
        build_pdf(path, doc["title"], doc["subtitle"], doc["sections"])
        console.print(f"[green]wrote[/green] {path}")


if __name__ == "__main__":
    main()
