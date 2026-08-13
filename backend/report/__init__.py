"""Cooling Action Plan report generation.

reportlab is imported lazily inside `build_report`, so this package can be
imported and its validation rules tested without the dependency present.
"""

from __future__ import annotations

from .pdf import (
    CONTENT_WIDTH,
    MARGIN,
    PAGE_HEIGHT,
    PAGE_WIDTH,
    Figure,
    ReportData,
    ReportError,
    ReportItem,
    build_report,
)

__all__ = [
    "CONTENT_WIDTH",
    "MARGIN",
    "PAGE_HEIGHT",
    "PAGE_WIDTH",
    "Figure",
    "ReportData",
    "ReportError",
    "ReportItem",
    "build_report",
]
