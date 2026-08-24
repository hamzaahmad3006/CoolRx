"""The Cooling Action Plan PDF endpoint.

`report/pdf.py` has always been able to build the document and had no route, so
the only way out of the app was a browser print. A print captures whatever the
client rendered; this is built from stored values by one code path, and it is the
only one that can *refuse* — the renderer will not emit a document whose headline
figures lack provenance.

These tests cover the assembly rules that keep that promise. The rendering itself
is covered by `test_report_pdf.py`.
"""

from __future__ import annotations

import pytest

from report.pdf import Figure, ReportData, ReportError, ReportItem, build_report


def _figure(label: str) -> Figure:
    return Figure(
        label=label,
        value="-1.60 C (-2.00 to -1.20)",
        source_type="catalog",
        source_detail="EPA Compendium Ch. 4 Table 2, https://example.test/doc",
    )


def _item(rank: int = 1) -> ReportItem:
    return ReportItem(
        rank=rank,
        tile_key="9tbq3d5qc",
        intervention_name="White single-ply PVC cool roof membrane",
        quantity="400 m2",
        cost="$6,564",
        predicted_delta="-1.60 C (-2.00 to -1.20)",
        hours_avoided="0.3",
    )


def _data(**overrides) -> ReportData:
    from datetime import UTC, datetime

    base = {
        "plan_id": "16feab98-ed66-4bd0-8487-d024ec7fecbb",
        "district": "Central Phoenix, AZ",
        "model_version": "trm-2026.08.22-a3f1",
        "created_at": datetime.now(UTC),
        "summary": None,
        "headline_figures": [_figure("Mean cooling across the district")],
        "items": [_item()],
        "provenance": [_figure("Mean cooling across the district")],
        "citations": ["EPA Compendium Chapter 4, Table 2."],
        "limitations": ["The model does not transfer to an unseen city."],
        "estimate_disclaimer": "Planning-grade estimate.",
        "verification_caveat": "Not evidence of causation.",
    }
    base.update(overrides)
    return ReportData(**base)


# ── what the renderer refuses ────────────────────────────────────────────────

def test_a_headline_figure_without_provenance_is_refused() -> None:
    """The rule the server path exists to enforce.

    A print stylesheet has no way to check this: it renders whatever the DOM
    holds. Here an untraceable figure stops the document being produced at all,
    rather than being printed and forwarded.
    """
    with pytest.raises(ReportError, match="no provenance record"):
        build_report(_data(provenance=[_figure("Something else entirely")]))


def test_a_plan_with_no_items_is_refused() -> None:
    with pytest.raises(ReportError, match="nothing to report"):
        build_report(_data(items=[]))


def test_a_report_without_citations_is_refused() -> None:
    """Every unit cost and effect size printed must carry its published source."""
    with pytest.raises(ReportError, match="catalog citations"):
        build_report(_data(citations=[]))


def test_a_report_without_the_estimate_disclaimer_is_refused() -> None:
    with pytest.raises(ReportError, match="disclaimer is required"):
        build_report(_data(estimate_disclaimer="   "))


# ── what it produces ─────────────────────────────────────────────────────────

def test_a_complete_plan_renders_a_pdf() -> None:
    pdf = build_report(_data())
    assert pdf.startswith(b"%PDF-")
    assert len(pdf) > 1000


def test_the_citation_is_reproduced_verbatim() -> None:
    """Summarising a citation makes it a paraphrase of a source the reader can no
    longer check. Extracted rather than searched as raw bytes: reportlab
    compresses its content streams."""
    from io import BytesIO

    from pypdf import PdfReader

    citation = (
        "Brousse O, Simpson C. Cool Roofs. Geophysical Research Letters 2024; "
        "51(13). doi:10.1029/2024GL109634"
    )
    pdf = build_report(_data(citations=[citation]))
    text = "\n".join(
        (page.extract_text() or "") for page in PdfReader(BytesIO(pdf)).pages
    )
    assert "10.1029/2024GL109634" in text


def test_limitations_reach_the_document() -> None:
    """A PDF carrying gentler caveats than the website is worse than one carrying
    none, because it looks as though it was checked."""
    from io import BytesIO

    from pypdf import PdfReader

    pdf = build_report(
        _data(limitations=["Predicted cooling for a material intervention is zero."])
    )
    text = "\n".join(
        (page.extract_text() or "") for page in PdfReader(BytesIO(pdf)).pages
    )
    assert "material intervention is zero" in text


def test_every_predicted_value_carries_its_interval() -> None:
    """There is no code path that renders a bare point estimate, so the item's
    delta string is passed through with its bounds already attached."""
    from io import BytesIO

    from pypdf import PdfReader

    pdf = build_report(_data())
    text = "\n".join(
        (page.extract_text() or "") for page in PdfReader(BytesIO(pdf)).pages
    )
    assert "-2.00 to -1.20" in text
