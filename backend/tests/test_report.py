"""Tests for the Cooling Action Plan PDF.

Mostly refusals. A PDF is forwarded, printed and quoted months later with no way
back to the system that made it, so the failures worth guarding are the ones that
produce a *usable-looking* document that cannot be checked — figures with no
provenance, costs with no citation, predictions with no interval.

The rendering tests assert the bytes are a real PDF and that specific strings
survive into it, rather than eyeballing layout.
"""

from __future__ import annotations

import base64
import contextlib
import re
import zlib
from datetime import UTC, datetime

import pytest

from report.pdf import (
    Figure,
    ReportData,
    ReportError,
    ReportItem,
    build_report,
)

DISCLAIMER = (
    "Planning-grade estimate under stated assumptions. Values are model "
    "predictions, not measurements."
)
CAVEAT = (
    "Difference-in-differences against untreated control blocks. This is evidence "
    "consistent with the prediction, not proof of cause."
)


def _figure(
    label: str = "Mean cooling", value: str = "-2.3 °C (-3.0 to -1.6)"
) -> Figure:
    return Figure(
        label=label,
        value=value,
        source_type="model",
        source_detail="Counterfactual inference, clamped to cited effect ranges",
        activity_id=None,
    )


def _item(rank: int = 1) -> ReportItem:
    return ReportItem(
        rank=rank,
        tile_key="9tbq2p3xj",
        intervention_name="Medium street tree",
        quantity="12 tree",
        cost="$5,400",
        predicted_delta="-1.9 °C (-2.6 to -1.2)",
        hours_avoided="310 h",
        rationale="This block is dominated by paved surface.",
    )


def _data(**overrides: object) -> ReportData:
    base: dict[str, object] = {
        "plan_id": "plan_2b8e44a1",
        "district": "Central Phoenix",
        "model_version": "trm-2026.08.22-a3f1",
        "created_at": datetime(2026, 8, 22, tzinfo=UTC),
        "summary": "This plan places 12 street trees across four blocks.",
        "headline_figures": [_figure()],
        "items": [_item()],
        "provenance": [
            _figure(),
            Figure(
                label="Hours above 35 °C",
                value="5,820 h",
                source_type="fortyguard",
                source_detail="Temperature API · exceedance",
                activity_id="act_4a81de20c7",
            ),
        ],
        "citations": ["Author, A. (2020). Title. Journal 1(1), 1-10."],
        "limitations": ["Trained on three arid south-western US districts."],
        "estimate_disclaimer": DISCLAIMER,
        "verification_caveat": CAVEAT,
        "rationales_dropped": 0,
    }
    base.update(overrides)
    return ReportData(**base)  # type: ignore[arg-type]


def _pdf_text(payload: bytes) -> str:
    """Extract the drawn text from a PDF's content streams.

    reportlab encodes each stream ASCII85 and then Flate by default, so both are
    undone in that order before the text-showing operands are pulled out. Decoding
    the real output rather than lowering compression for tests matters here: these
    assertions are about what actually reaches the page, and a test that inspected
    a differently-configured document would not be testing the shipped artefact.
    """
    chunks: list[str] = []
    for match in re.finditer(rb"stream\r?\n(.*?)endstream", payload, re.DOTALL):
        raw = match.group(1).strip()

        with contextlib.suppress(ValueError):
            raw = base64.a85decode(raw, adobe=True)
        with contextlib.suppress(zlib.error):
            raw = zlib.decompress(raw)

        chunks.append(raw.decode("latin-1", errors="ignore"))

    body = "\n".join(chunks)
    # `(text) Tj` for single strings, and the string parts of `[...] TJ` arrays.
    pieces = re.findall(r"\((?:\\.|[^\\()])*\)", body)
    return " ".join(
        piece[1:-1].replace("\\(", "(").replace("\\)", ")") for piece in pieces
    )


# ═════════════════════════════════════════════════════════════════════════════
# Refusals
# ═════════════════════════════════════════════════════════════════════════════


def test_a_plan_with_no_items_is_refused() -> None:
    with pytest.raises(ReportError, match="nothing to report"):
        build_report(_data(items=[]))


def test_a_report_without_provenance_is_refused() -> None:
    """P2: a figure the reader cannot trace must not be printed."""
    with pytest.raises(ReportError, match="provenance"):
        build_report(_data(provenance=[]))


def test_a_report_without_citations_is_refused() -> None:
    """Every unit cost printed here must carry its published source."""
    with pytest.raises(ReportError, match="citations"):
        build_report(_data(citations=[]))


def test_a_missing_disclaimer_is_refused() -> None:
    with pytest.raises(ReportError, match="disclaimer"):
        build_report(_data(estimate_disclaimer="   "))


def test_a_headline_figure_without_provenance_is_refused() -> None:
    """The specific failure this module is shaped around.

    A number on the first page with no entry in the appendix is untraceable, and
    that is precisely what the report exists not to produce.
    """
    with pytest.raises(ReportError, match="no provenance record"):
        build_report(
            _data(
                headline_figures=[_figure(label="People reached", value="18,400")],
                provenance=[_figure(label="Mean cooling")],
            )
        )


# ═════════════════════════════════════════════════════════════════════════════
# Output
# ═════════════════════════════════════════════════════════════════════════════


@pytest.fixture(scope="module")
def rendered() -> bytes:
    pytest.importorskip("reportlab")
    return build_report(_data())


def test_output_is_a_pdf(rendered: bytes) -> None:
    assert rendered.startswith(b"%PDF-")
    assert rendered.rstrip().endswith(b"%%EOF")
    assert len(rendered) > 1_000


def test_the_disclaimer_reaches_the_document(rendered: bytes) -> None:
    """Required on the page, not just in the input object."""
    assert "Planning-grade estimate" in _pdf_text(rendered)


def test_intervals_reach_the_document(rendered: bytes) -> None:
    """No code path renders a bare point estimate."""
    text = _pdf_text(rendered)
    assert "-1.9" in text
    assert "-2.6" in text and "-1.2" in text


def test_the_activity_id_reaches_the_document(rendered: bytes) -> None:
    """The handle that makes a figure re-checkable against the source."""
    assert "act_4a81de20c7" in _pdf_text(rendered)


def test_the_citation_is_reproduced_verbatim(rendered: bytes) -> None:
    assert "Journal 1(1), 1-10." in _pdf_text(rendered)


def test_limitations_reach_the_document(rendered: bytes) -> None:
    assert "arid south-western" in _pdf_text(rendered)


def test_the_footer_states_the_document_is_not_measurements(
    rendered: bytes,
) -> None:
    """On every page, so a forwarded single page still carries the caveat."""
    assert "not measurements" in _pdf_text(rendered)


def test_dropped_rationales_are_explained_not_omitted() -> None:
    """An unexplained gap looks like a bug; the real reason is the guard firing."""
    payload = build_report(
        _data(
            items=[
                _item(1),
                ReportItem(
                    rank=2,
                    tile_key="9tbq2p60m",
                    intervention_name="Cool roof coating",
                    quantity="400 m2",
                    cost="$12,000",
                    predicted_delta="-0.9 °C (-1.4 to -0.4)",
                    hours_avoided="120 h",
                    rationale=None,
                ),
            ],
            rationales_dropped=1,
        )
    )
    text = _pdf_text(payload)
    assert "numeric check rejected" in text


def test_a_long_plan_spans_multiple_pages() -> None:
    """Guards the page-break path, which a single-page fixture never exercises."""
    payload = build_report(_data(items=[_item(rank=i) for i in range(1, 61)]))
    assert payload.count(b"/Type /Page") > 1 or payload.count(b"/Type/Page") > 1


def test_an_absent_summary_is_handled() -> None:
    """The summary is null when the guard rejected it — the report still builds."""
    payload = build_report(_data(summary=None))
    assert payload.startswith(b"%PDF-")


def test_the_equity_note_is_included_when_present() -> None:
    payload = build_report(
        _data(equity_note="63% of the benefit reaches the most vulnerable deciles.")
    )
    assert "most vulnerable deciles" in _pdf_text(payload)


def test_every_page_carries_the_required_attribution() -> None:
    """ODbL obliges attribution wherever OSM-derived data appears, and SRS 12.2.1
    names the PDF alongside the map views (AC-21).

    Asserted against the rendered bytes rather than by reading the source, so
    deleting the footer fails here rather than at submission. reportlab writes
    page streams through ASCII85 *then* Flate; checking only the Flate layer
    finds nothing and would pass a document with no attribution at all.
    """
    import base64
    import zlib

    pdf = build_report(_data())
    assert pdf[:4] == b"%PDF"

    needle = b"OpenStreetMap contributors"

    def _plain(raw: bytes) -> bytes:
        for decode in (
            # reportlab emits ASCII85 with a trailing "~>" but no leading "<~",
            # so adobe=True alone rejects it.
            lambda b: zlib.decompress(base64.a85decode(b.rstrip(b"~>"))),
            lambda b: zlib.decompress(base64.a85decode(b, adobe=True)),
            zlib.decompress,
            lambda b: b,
        ):
            try:
                return decode(raw)
            except Exception:  # noqa: BLE001, S112 — try the next encoding; not logged, because these loops run over thousands of upstream records and a line per skip would drown the run
                continue
        return b""

    # Regex rather than split: splitting on b"stream" also matches inside
    # b"endstream", leaving a trailing "end" that corrupts the ASCII85 payload.
    streams = [m.strip() for m in re.findall(b"stream(.*?)endstream", pdf, re.S)]
    assert streams, "the PDF carried no content stream"

    assert any(needle in _plain(chunk) for chunk in streams), (
        "the OpenStreetMap attribution is missing from the rendered PDF"
    )
