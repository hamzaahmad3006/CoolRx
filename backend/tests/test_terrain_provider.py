"""Elevation provider tests. Offline — the DEM fetch is stubbed.

Verified live on 2026-08-21 over the Phoenix AOI: elevation 331.33-331.59 m across
four tiles with within-tile relief of 0.82-4.33 m, which is what a flat desert city
on a river plain should read.
"""

from __future__ import annotations

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_bounds

from geo.grid import Tile
from geo.terrain import ElevationProvider

WEST, SOUTH, EAST, NORTH = -112.0780, 33.4480, -112.0740, 33.4520


def _tile(key: str, w: float, s: float, e: float, n: float) -> Tile:
    return Tile(
        tile_key=key, west=w, south=s, east=e, north=n,
        centroid_lon=(w + e) / 2, centroid_lat=(s + n) / 2,
    )


def _raster(values: np.ndarray):
    height, width = values.shape
    memfile = rasterio.io.MemoryFile()
    with memfile.open(
        driver="GTiff", height=height, width=width, count=1,
        dtype="float32", crs="EPSG:4326",
        transform=from_bounds(WEST, SOUTH, EAST, NORTH, width, height),
    ) as dst:
        dst.write(values.astype("float32"), 1)
    ds = memfile.open()
    return ds, ds.read(1)


@pytest.fixture
def provider(monkeypatch):
    def _make(values: np.ndarray):
        p = ElevationProvider()
        monkeypatch.setattr(p, "_fetch_dem", lambda *a, **k: _raster(values))
        return p
    return _make


def _whole() -> Tile:
    return _tile("t", WEST, SOUTH, EAST, NORTH)


def test_elevation_is_the_mean_of_the_covered_cells(provider):
    p = provider(np.full((4, 4), 331.5, dtype="float32"))
    result = p.fetch([_whole()])
    assert result.values["t"]["elevation_m"] == pytest.approx(331.5, abs=0.01)


def test_local_relief_is_the_spread_within_the_tile(provider):
    """Not a neighbourhood window — the question is whether this tile is flat."""
    values = np.array(
        [[330.0, 330.0, 331.0, 331.0],
         [330.0, 330.0, 331.0, 331.0],
         [332.0, 332.0, 335.0, 335.0],
         [332.0, 332.0, 335.0, 335.0]], dtype="float32",
    )
    p = provider(values)
    result = p.fetch([_whole()])
    assert result.values["t"]["local_relief_m"] == pytest.approx(5.0, abs=0.01)


def test_a_flat_tile_reports_zero_relief_not_null(provider):
    """Zero relief is a measurement: this ground is flat."""
    p = provider(np.full((4, 4), 331.0, dtype="float32"))
    result = p.fetch([_whole()])
    assert result.values["t"]["local_relief_m"] == 0.0


def test_void_sentinels_are_excluded_before_any_statistic(provider):
    """A single -3.4e38 in the window would make both the mean and the relief
    absurd. Voids leave before the mean is taken, not after."""
    values = np.array(
        [[331.0, 331.0, 331.0, 331.0],
         [331.0, 331.0, 331.0, 331.0],
         [-3.4e38, -3.4e38, -3.4e38, -3.4e38],
         [-3.4e38, -3.4e38, -3.4e38, -3.4e38]], dtype="float32",
    )
    p = provider(values)
    result = p.fetch([_whole()])
    assert result.values["t"]["elevation_m"] == pytest.approx(331.0, abs=0.01)
    assert result.values["t"]["local_relief_m"] == 0.0


def test_an_all_void_tile_answers_null(provider):
    p = provider(np.full((4, 4), -3.4e38, dtype="float32"))
    result = p.fetch([_whole()])
    assert result.values["t"]["elevation_m"] is None
    assert result.misses["t"]


def test_a_tile_outside_the_dem_is_a_miss(provider):
    p = provider(np.full((4, 4), 331.0, dtype="float32"))
    result = p.fetch([_tile("far", -80.0, 25.0, -79.99, 25.01)])
    assert result.values["far"]["elevation_m"] is None


def test_a_transport_failure_yields_misses_rather_than_raising(monkeypatch):
    """3DEP returned 504 from every data endpoint on 2026-08-20 while its metadata
    endpoint answered normally. A national service being briefly unwell must not
    take a diagnosis down with it."""
    p = ElevationProvider()

    def _boom(*a, **k):
        raise ConnectionError("3DEP unreachable")

    monkeypatch.setattr(p, "_fetch_dem", _boom)
    result = p.fetch([_whole()])
    assert result.values == {}
    assert result.misses["t"].startswith("elevation unavailable")


def test_an_empty_batch_makes_no_request(monkeypatch):
    p = ElevationProvider()
    monkeypatch.setattr(
        p, "_fetch_dem",
        lambda *a, **k: pytest.fail("no request should be made for zero tiles"),
    )
    assert p.fetch([]).values == {}


def test_provenance_names_3dep() -> None:
    info = ElevationProvider().info
    assert "3DEP" in info.source
    assert info.resolution_m == 10.0
