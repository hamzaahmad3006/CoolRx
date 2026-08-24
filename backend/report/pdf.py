"""Cooling Action Plan PDF (SRS §12).

The artefact that leaves the building. A screen can be re-checked against the
system that produced it; a PDF is forwarded, printed and quoted months later with
no way back to the source. Everything here follows from that.

  * **Every figure is formatted once**, by `format_value`, so the number in the
    table and the number in the provenance appendix cannot differ by a rounding.
  * **The provenance appendix is not optional.** A figure without a traceable
    source does not get printed; `build_report` raises rather than emitting one.
  * **Citations are reproduced verbatim** from the catalog, not summarised.
  * **Every predicted value carries its interval.** There is no code path that
    renders a bare point estimate.

Uses reportlab's low-level canvas rather than a template engine. The document is a
fixed sequence of blocks, and the flowable machinery would add a dependency layer
whose page-break behaviour is harder to reason about than explicit cursor
management.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from io import BytesIO
from typing import Final

import structlog

log = structlog.get_logger(__name__)

# ── Page geometry, in points (72 per inch) ───────────────────────────────────
PAGE_WIDTH: Final[float] = 595.27  # A4
PAGE_HEIGHT: Final[float] = 841.89
MARGIN: Final[float] = 56.0
CONTENT_WIDTH: Final[float] = PAGE_WIDTH - 2 * MARGIN

BODY_SIZE: Final[float] = 9.5
SMALL_SIZE: Final[float] = 8.0
LEADING: Final[float] = 13.0

#: Required attribution, rendered on every page.
#:
#: ODbL obliges attribution wherever OSM-derived data appears, and SRS §12.2.1
#: names the PDF explicitly alongside the map views. The frontend already carries
#: the same string via BRAND.attribution; this is the other half of AC-21. It sits
#: in the footer rather than a credits page so it cannot be lost by printing or
#: sharing a single sheet.
ATTRIBUTION: Final[str] = "© OpenStreetMap contributors · Temperature data © FortyGuard"

INK = (0.09, 0.09, 0.10)
MUTED = (0.42, 0.43, 0.45)
RULE = (0.85, 0.85, 0.83)


class ReportError(RuntimeError):
    """The report cannot be produced as specified."""


@dataclass(frozen=True, slots=True)
class Figure:
    """One printed number, with its provenance.

    `value` is pre-formatted text rather than a float. The report never formats a
    number itself — it prints the same string the UI showed, so the PDF and the
    screen cannot disagree through separate rounding.
    """

    label: str
    value: str
    source_type: str
    source_detail: str
    activity_id: str | None = None


@dataclass(frozen=True, slots=True)
class ReportItem:
    rank: int
    tile_key: str
    intervention_name: str
    quantity: str
    cost: str
    #: Pre-formatted including its interval, e.g. "-1.9 °C (-2.6 to -1.2)".
    predicted_delta: str
    hours_avoided: str
    rationale: str | None = None


@dataclass(slots=True)
class ReportData:
    plan_id: str
    district: str
    model_version: str
    created_at: datetime
    summary: str | None
    headline_figures: list[Figure]
    items: list[ReportItem]
    provenance: list[Figure]
    #: Reproduced verbatim from `interventions_catalog.source_citation`.
    citations: list[str]
    limitations: list[str]
    estimate_disclaimer: str
    verification_caveat: str
    #: Count of items whose rationale the guard rejected.
    rationales_dropped: int = 0
    equity_note: str | None = None
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


def build_report(data: ReportData) -> bytes:
    """Render the plan to PDF bytes.

    Raises rather than emitting a document that cannot stand on its own: a report
    with figures but no provenance, or with an uncited catalog, is exactly the
    artefact this project exists not to produce.
    """
    _validate(data)

    from reportlab.pdfgen import canvas

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    pdf.setTitle(f"Cooling Action Plan — {data.district}")
    pdf.setAuthor("CoolRx")
    pdf.setSubject("Planning-grade urban cooling estimates")

    cursor = _Cursor(pdf)

    _cover(cursor, data)
    _headline(cursor, data)
    _schedule(cursor, data)
    _rationales(cursor, data)
    _verification(cursor, data)
    _provenance(cursor, data)
    _citations(cursor, data)
    _limitations(cursor, data)

    cursor.finish()
    pdf.save()

    payload = buffer.getvalue()
    log.info(
        "report.built",
        plan_id=data.plan_id,
        bytes=len(payload),
        items=len(data.items),
        figures=len(data.provenance),
    )
    return payload


def _validate(data: ReportData) -> None:
    if not data.items:
        raise ReportError(
            "A plan with no interventions has nothing to report. Refusing to "
            "produce an empty document."
        )
    if not data.provenance:
        raise ReportError(
            "No provenance records. Every figure in this report must trace to a "
            "source (principle P2), so a report without them cannot be produced."
        )
    if not data.citations:
        raise ReportError(
            "No catalog citations. Every unit cost and effect size printed here "
            "must carry its published source."
        )
    if not data.estimate_disclaimer.strip():
        raise ReportError(
            "The estimate disclaimer is required on every page carrying a "
            "predicted figure."
        )

    # A headline figure with no provenance entry would be a number the reader
    # cannot trace, which is the failure this whole module is shaped around.
    traced = {figure.label for figure in data.provenance}
    untraced = [f.label for f in data.headline_figures if f.label not in traced]
    if untraced:
        raise ReportError(
            f"These headline figures have no provenance record: {untraced}. "
            "Add them, or remove the figures."
        )


# ═════════════════════════════════════════════════════════════════════════════
# Layout
# ═════════════════════════════════════════════════════════════════════════════


class _Cursor:
    """Explicit page cursor.

    Every write asks for the vertical space it needs first, so a block breaks to a
    new page as a unit instead of splitting a heading from its content.
    """

    def __init__(self, pdf: object) -> None:
        self._pdf = pdf
        self.y = PAGE_HEIGHT - MARGIN
        self.page = 1
        self._stamp_footer()

    def space(self, points: float) -> None:
        self.y -= points

    def need(self, points: float) -> None:
        if self.y - points < MARGIN + 28:
            self.new_page()

    def new_page(self) -> None:
        self._pdf.showPage()  # type: ignore[attr-defined]
        self.page += 1
        self.y = PAGE_HEIGHT - MARGIN
        self._stamp_footer()

    def finish(self) -> None:
        pass

    def _stamp_footer(self) -> None:
        pdf = self._pdf
        pdf.setFillColorRGB(*MUTED)  # type: ignore[attr-defined]
        pdf.setFont("Helvetica", 7.5)  # type: ignore[attr-defined]
        pdf.drawString(  # type: ignore[attr-defined]
            MARGIN,
            MARGIN - 16,
            "CoolRx · planning-grade estimates, not measurements",
        )
        # Centred so it survives on a page whose left note is long, and drawn on
        # every page for the same reason the frontend draws it on every view.
        pdf.setFont("Helvetica", 6.5)  # type: ignore[attr-defined]
        pdf.drawCentredString(  # type: ignore[attr-defined]
            PAGE_WIDTH / 2, MARGIN - 26, ATTRIBUTION
        )
        pdf.setFont("Helvetica", 7.5)  # type: ignore[attr-defined]
        pdf.drawRightString(  # type: ignore[attr-defined]
            PAGE_WIDTH - MARGIN, MARGIN - 16, str(self.page)
        )
        pdf.setFillColorRGB(*INK)  # type: ignore[attr-defined]

    # ── Primitives ───────────────────────────────────────────────────────────

    def heading(self, text: str, size: float = 13.0) -> None:
        self.need(size + 18)
        self._pdf.setFont("Helvetica-Bold", size)  # type: ignore[attr-defined]
        self._pdf.setFillColorRGB(*INK)  # type: ignore[attr-defined]
        self._pdf.drawString(MARGIN, self.y, text)  # type: ignore[attr-defined]
        self.space(size + 8)

    def eyebrow(self, text: str) -> None:
        self.need(16)
        self._pdf.setFont("Helvetica-Bold", 7.0)  # type: ignore[attr-defined]
        self._pdf.setFillColorRGB(*MUTED)  # type: ignore[attr-defined]
        self._pdf.drawString(MARGIN, self.y, text.upper())  # type: ignore[attr-defined]
        self.space(11)

    def paragraph(
        self, text: str, *, size: float = BODY_SIZE, muted: bool = False
    ) -> None:
        for line in _wrap(text, size, CONTENT_WIDTH):
            self.need(LEADING)
            self._pdf.setFont("Helvetica", size)  # type: ignore[attr-defined]
            self._pdf.setFillColorRGB(*(MUTED if muted else INK))  # type: ignore[attr-defined]
            self._pdf.drawString(MARGIN, self.y, line)  # type: ignore[attr-defined]
            self.space(LEADING)
        self.space(4)

    def rule(self) -> None:
        self.need(8)
        self._pdf.setStrokeColorRGB(*RULE)  # type: ignore[attr-defined]
        self._pdf.setLineWidth(0.5)  # type: ignore[attr-defined]
        self._pdf.line(MARGIN, self.y, PAGE_WIDTH - MARGIN, self.y)  # type: ignore[attr-defined]
        self.space(10)

    def row(self, cells: list[tuple[str, float, bool]], *, bold: bool = False) -> None:
        """One table row: (text, x-offset, right-aligned)."""
        self.need(LEADING)
        font = "Helvetica-Bold" if bold else "Helvetica"
        self._pdf.setFont(font, SMALL_SIZE)  # type: ignore[attr-defined]
        self._pdf.setFillColorRGB(*INK)  # type: ignore[attr-defined]
        for text, offset, right in cells:
            x = MARGIN + offset
            if right:
                self._pdf.drawRightString(x, self.y, text)  # type: ignore[attr-defined]
            else:
                self._pdf.drawString(x, self.y, _truncate(text, offset))  # type: ignore[attr-defined]
        self.space(LEADING)


def _wrap(text: str, size: float, width: float) -> list[str]:
    """Greedy wrap using an average-character-width estimate.

    Approximate rather than exact metric measurement, which is acceptable because
    the margin absorbs the error; the alternative needs a font-metrics round-trip
    per word for a document nobody edits interactively.
    """
    per_char = size * 0.5
    max_chars = max(20, int(width / per_char))

    lines: list[str] = []
    for paragraph in text.split("\n"):
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        current = words[0]
        for word in words[1:]:
            if len(current) + 1 + len(word) <= max_chars:
                current = f"{current} {word}"
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines


def _truncate(text: str, offset: float) -> str:
    budget = int((CONTENT_WIDTH - offset) / (SMALL_SIZE * 0.5))
    return text if len(text) <= budget else f"{text[: max(1, budget - 1)]}…"


# ═════════════════════════════════════════════════════════════════════════════
# Sections
# ═════════════════════════════════════════════════════════════════════════════


def _cover(cursor: _Cursor, data: ReportData) -> None:
    cursor.eyebrow("Cooling Action Plan")
    cursor.heading(data.district, size=19.0)
    cursor.paragraph(
        f"Plan {data.plan_id} · model {data.model_version} · generated "
        f"{data.generated_at.strftime('%Y-%m-%d')}",
        size=SMALL_SIZE,
        muted=True,
    )
    cursor.rule()

    if data.summary is not None:
        cursor.paragraph(data.summary)
        cursor.space(2)

    # The caveat appears before any figure, not after them.
    cursor.paragraph(data.estimate_disclaimer, size=SMALL_SIZE, muted=True)
    cursor.rule()


def _headline(cursor: _Cursor, data: ReportData) -> None:
    cursor.eyebrow("Predicted impact")
    for figure in data.headline_figures:
        cursor.row(
            [
                (figure.label, 0.0, False),
                (figure.value, CONTENT_WIDTH, True),
            ]
        )
    cursor.space(6)


def _schedule(cursor: _Cursor, data: ReportData) -> None:
    cursor.heading("Interventions, in priority order")

    columns: list[tuple[str, float, bool]] = [
        ("#", 0.0, False),
        ("Block", 22.0, False),
        ("Intervention", 90.0, False),
        ("Qty", 300.0, True),
        ("Cost", 370.0, True),
        ("Predicted ΔT", CONTENT_WIDTH, True),
    ]
    cursor.row(columns, bold=True)
    cursor.rule()

    for item in data.items:
        cursor.row(
            [
                (str(item.rank).rjust(2, "0"), 0.0, False),
                (item.tile_key, 22.0, False),
                (item.intervention_name, 90.0, False),
                (item.quantity, 300.0, True),
                (item.cost, 370.0, True),
                (item.predicted_delta, CONTENT_WIDTH, True),
            ]
        )

    cursor.space(6)
    cursor.paragraph(
        "Every temperature change above is shown with its prediction interval. "
        "The interval reflects model uncertainty only; it does not cover "
        "construction quality, maintenance, or weather in any future year.",
        size=SMALL_SIZE,
        muted=True,
    )


def _rationales(cursor: _Cursor, data: ReportData) -> None:
    written = [item for item in data.items if item.rationale is not None]
    if not written and data.rationales_dropped == 0:
        return

    cursor.heading("Why these blocks")
    for item in written:
        cursor.eyebrow(f"{item.tile_key} · {item.intervention_name}")
        cursor.paragraph(item.rationale or "")

    # Stated plainly rather than left as an unexplained absence: a dropped
    # rationale means the numeric guard caught the language model inventing a
    # figure, which is the mechanism working.
    if data.rationales_dropped > 0:
        cursor.paragraph(
            f"{data.rationales_dropped} of {len(data.items)} interventions have no "
            "written explanation. The automated numeric check rejected the "
            "generated text for those, so it was discarded rather than printed. "
            "The figures are unaffected — none of them originate from the language "
            "model.",
            size=SMALL_SIZE,
            muted=True,
        )


def _verification(cursor: _Cursor, data: ReportData) -> None:
    cursor.heading("How to check whether it worked")
    cursor.paragraph(
        "Re-measure the same blocks one season after installation, at the same "
        "hour of day and the same resolution as the baseline. Compare the change "
        "against untreated control blocks matched on baseline temperature and "
        "land cover. The treated and control blocks are fixed in advance so they "
        "cannot be selected afterwards to favour the result."
    )
    cursor.paragraph(data.verification_caveat, size=SMALL_SIZE, muted=True)


def _provenance(cursor: _Cursor, data: ReportData) -> None:
    cursor.heading("Where every figure came from")
    cursor.paragraph(
        "Each number in this document traces to one of: a measurement from the "
        "FortyGuard Temperature API identified by its activity id, a published "
        "cost or effect size from the appendix, a model prediction, or arithmetic "
        "over those.",
        size=SMALL_SIZE,
        muted=True,
    )

    for figure in data.provenance:
        cursor.need(LEADING * 3)
        cursor.row(
            [
                (figure.label, 0.0, False),
                (figure.value, CONTENT_WIDTH, True),
            ],
            bold=True,
        )
        detail = f"{figure.source_type} · {figure.source_detail}"
        if figure.activity_id is not None:
            detail = f"{detail} · activity {figure.activity_id}"
        cursor.paragraph(detail, size=7.5, muted=True)


def _citations(cursor: _Cursor, data: ReportData) -> None:
    cursor.heading("Sources for costs and effect sizes")
    cursor.paragraph(
        "Reproduced verbatim from the intervention catalog. Every unit cost and "
        "cooling range used in this plan carries one.",
        size=SMALL_SIZE,
        muted=True,
    )
    for index, citation in enumerate(data.citations, start=1):
        cursor.paragraph(f"{index}. {citation}", size=SMALL_SIZE)


def _limitations(cursor: _Cursor, data: ReportData) -> None:
    cursor.heading("Limitations")
    for limitation in data.limitations:
        cursor.paragraph(f"— {limitation}", size=SMALL_SIZE)

    if data.equity_note is not None:
        cursor.space(4)
        cursor.eyebrow("Equity")
        cursor.paragraph(data.equity_note, size=SMALL_SIZE)
