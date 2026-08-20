"""Land-cover provider tests.

Offline — the WCS call is stubbed. Verified live on 2026-08-20: downtown Phoenix
returned 0% grass/shrub across four tiles (classes 22/23/24, all developed) while a
Papago Park tile returned 87.37%. That contrast is the real proof the class codes are
being read rather than palette indices; it cannot be asserted here without calling
mrlc.gov on every run.
"""

from __future__ import annotations

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_bounds

from geo.grid import Tile
from geo.landcover import LandCoverProvider

WEST, SOUTH, EAST, NORTH = -112.0780, 33.4480, -112.0740, 33.4520


def _tile(key: str, w: float, s: float, e: float, n: float) -> Tile:
    return Tile(
        tile_key=key, west=w, south=s, east=e, north=n,
        centroid_lon=(w + e) / 2, centroid_lat=(s + n) / 2,
    )


def _raster(values: np.ndarray):
    height, width = values.shape
    transform = from_bounds(WEST, SOUTH, EAST, NORTH, width, height)
    memfile = rasterio.io.MemoryFile()
    with memfile.open(
        driver="GTiff", height=height, width=width, count=1,
        dtype=values.dtype, crs="EPSG:4326", transform=transform,
    ) as dst:
        dst.write(values, 1)
    dataset = memfile.open()
    return dataset, dataset.read(1)


@pytest.fixture
def provider(monkeypatch):
    def _make(values: np.ndarray):
        p = LandCoverProvider()
        monkeypatch.setattr(p, "_fetch_coverage", lambda *a, **k: _raster(values))
        return p
    return _make


def _whole_tile() -> Tile:
    return _tile("t", WEST, SOUTH, EAST, NORTH)


# ── class fractions ──────────────────────────────────────────────────────────

def test_all_developed_reads_zero_for_both_fields(provider):
    """Downtown: classes 22/23/24. Zero here is a measurement, not a gap."""
    p = provider(np.full((4, 4), 24, dtype="uint8"))
    result = p.fetch([_whole_tile()])
    assert result.values["t"] == {"water_pct": 0.0, "grass_shrub_pct": 0.0}


def test_open_water_is_counted(provider):
    values = np.array(
        [[11, 11, 24, 24],
         [11, 11, 24, 24],
         [24, 24, 24, 24],
         [24, 24, 24, 24]], dtype="uint8",
    )
    p = provider(values)
    result = p.fetch([_whole_tile()])
    assert result.values["t"]["water_pct"] == pytest.approx(25.0, abs=0.1)


def test_grass_and_shrub_are_both_counted(provider):
    """52 shrub/scrub and 71 grassland/herbaceous, together."""
    values = np.array(
        [[52, 52, 71, 71],
         [24, 24, 24, 24],
         [24, 24, 24, 24],
         [24, 24, 24, 24]], dtype="uint8",
    )
    p = provider(values)
    result = p.fetch([_whole_tile()])
    assert result.values["t"]["grass_shrub_pct"] == pytest.approx(25.0, abs=0.1)


def test_pasture_and_crops_are_not_grass_shrub(provider):
    """81 pasture and 82 cultivated crops are agricultural cover. The feature is
    named grass and shrub, and counting farmland in it would misdescribe the
    surface an intervention would change."""
    values = np.full((4, 4), 81, dtype="uint8")
    values[0, :] = 82
    p = provider(values)
    result = p.fetch([_whole_tile()])
    assert result.values["t"]["grass_shrub_pct"] == 0.0


def test_perennial_ice_is_not_water(provider):
    """Class 12 is ice and snow. It is not water in any sense that cools a
    street, so it is excluded from water_pct."""
    p = provider(np.full((4, 4), 12, dtype="uint8"))
    result = p.fetch([_whole_tile()])
    assert result.values["t"]["water_pct"] == 0.0


# ── the denominator ──────────────────────────────────────────────────────────

def test_invalid_values_leave_the_denominator(provider):
    """Half the window is fill. Two water cells out of eight *valid* ones is 25%,
    not 12.5% — counting fill as 'not water' would deflate every fraction."""
    values = np.array(
        [[11, 11, 24, 24],
         [24, 24, 24, 24],
         [250, 250, 250, 250],
         [255, 255, 255, 255]], dtype="uint8",
    )
    p = provider(values)
    result = p.fetch([_whole_tile()])
    assert result.values["t"]["water_pct"] == pytest.approx(25.0, abs=0.1)


def test_a_window_of_only_invalid_values_answers_null(provider):
    """Null, not zero: no class was read, so nothing is known about the surface."""
    p = provider(np.full((4, 4), 255, dtype="uint8"))
    result = p.fetch([_whole_tile()])
    assert result.values["t"]["water_pct"] is None
    assert result.values["t"]["grass_shrub_pct"] is None
    assert result.misses["t"]


def test_a_tile_outside_the_coverage_is_a_miss(provider):
    p = provider(np.full((4, 4), 24, dtype="uint8"))
    result = p.fetch([_tile("far", -80.0, 25.0, -79.99, 25.01)])
    assert result.values["far"]["water_pct"] is None
    assert result.misses


# ── failure and contract ─────────────────────────────────────────────────────

def test_a_transport_failure_yields_misses_rather_than_raising(monkeypatch):
    p = LandCoverProvider()

    def _boom(*a, **k):
        raise ConnectionError("mrlc.gov unreachable")

    monkeypatch.setattr(p, "_fetch_coverage", _boom)
    result = p.fetch([_whole_tile()])
    assert result.values == {}
    assert result.misses["t"].startswith("land cover unavailable")


def test_an_empty_batch_makes_no_request(monkeypatch):
    p = LandCoverProvider()
    monkeypatch.setattr(
        p, "_fetch_coverage",
        lambda *a, **k: pytest.fail("no request should be made for zero tiles"),
    )
    assert p.fetch([]).values == {}


def test_albedo_is_not_claimed() -> None:
    """The class layer could supply it, but only with a per-class reflectance
    table from a citable source. Albedo feeds a predicted temperature reduction a
    city would spend money on, so an uncited constant is not acceptable."""
    assert "albedo_proxy" not in LandCoverProvider().fields


def test_the_year_selects_the_coverage() -> None:
    assert LandCoverProvider(year=2019)._coverage == (
        "mrlc_display__NLCD_2019_Land_Cover_L48"
    )


def test_provenance_names_wcs() -> None:
    """WMS returns palette indices for this layer; WCS returns class codes. The
    Methods page should record which one produced the numbers."""
    info = LandCoverProvider().info
    assert "WCS" in info.source
    assert info.resolution_m == 30.0
