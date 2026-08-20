"""MRLC provider tests.

None of these touch the network. `conftest.py` pins the suite offline, and a test
that reached mrlc.gov would be slow, flaky, and would hammer a free public service
on every run. The HTTP call is stubbed; what is exercised is the part that can
actually be wrong — window sampling, no-data handling, and failure behaviour.

The one thing tests cannot prove is that the live layer still returns what it
returned on 2026-08-19. That was verified by hand against the Phoenix AOI
(impervious 78.5-91.3%, canopy 0-0.6%) and is recorded in the module docstring.
"""

from __future__ import annotations

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_bounds

from geo.grid import Tile
from geo.mrlc import ImperviousProvider, TreeCanopyProvider

# A 4x4 raster over a 0.004 x 0.004 degree box, so each cell is 0.001 deg square.
WEST, SOUTH, EAST, NORTH = -112.0780, 33.4480, -112.0740, 33.4520


def _tile(key: str, w: float, s: float, e: float, n: float) -> Tile:
    return Tile(
        tile_key=key, west=w, south=s, east=e, north=n,
        centroid_lon=(w + e) / 2, centroid_lat=(s + n) / 2,
    )


def _raster(values: np.ndarray):
    """An in-memory dataset over the fixed box, plus its band."""
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
    """An ImperviousProvider whose raster is supplied rather than fetched."""
    def _make(values: np.ndarray):
        p = ImperviousProvider()
        monkeypatch.setattr(p, "_fetch_raster", lambda *a, **k: _raster(values))
        return p
    return _make


# ── sampling ─────────────────────────────────────────────────────────────────

def test_a_tile_averages_the_cells_it_covers(provider) -> None:
    """A tile spans several 30 m cells, so the feature is their mean.

    Sampling the centroid instead would throw away three quarters of a 60 m tile
    and make the value depend on where the grid happened to land.
    """
    p = provider(np.full((4, 4), 80, dtype="uint8"))
    result = p.fetch([_tile("t", WEST, SOUTH, EAST, NORTH)])
    assert result.values["t"]["impervious_pct"] == 80.0


def test_the_mean_reflects_variation_across_the_tile(provider) -> None:
    values = np.array(
        [[100, 100, 0, 0],
         [100, 100, 0, 0],
         [100, 100, 0, 0],
         [100, 100, 0, 0]], dtype="uint8",
    )
    p = provider(values)
    result = p.fetch([_tile("t", WEST, SOUTH, EAST, NORTH)])
    assert result.values["t"]["impervious_pct"] == pytest.approx(50.0, abs=1.0)


def test_no_data_is_dropped_rather_than_averaged_in(provider) -> None:
    """NLCD fills with 250-255. Averaging those into a percentage would invent
    an impossible value — 255% impervious is not a measurement."""
    values = np.array(
        [[60, 60, 255, 255],
         [60, 60, 255, 255],
         [60, 60, 255, 255],
         [60, 60, 255, 255]], dtype="uint8",
    )
    p = provider(values)
    result = p.fetch([_tile("t", WEST, SOUTH, EAST, NORTH)])
    assert result.values["t"]["impervious_pct"] == 60.0


def test_a_tile_of_only_no_data_answers_null_not_zero(provider) -> None:
    """Null and zero are different claims: one is 'unknown', the other is
    'measured, and there is no pavement here'."""
    p = provider(np.full((4, 4), 255, dtype="uint8"))
    result = p.fetch([_tile("t", WEST, SOUTH, EAST, NORTH)])
    assert result.values["t"]["impervious_pct"] is None
    assert "t" in result.misses


def test_a_tile_outside_the_raster_is_a_miss_not_a_crash(provider) -> None:
    p = provider(np.full((4, 4), 70, dtype="uint8"))
    far = _tile("far", -80.0, 25.0, -79.99, 25.01)
    result = p.fetch([far])
    assert result.values["far"]["impervious_pct"] is None
    assert result.misses


# ── failure behaviour ────────────────────────────────────────────────────────

def test_a_transport_failure_yields_misses_rather_than_raising(monkeypatch) -> None:
    """`fetch` must not raise on partial coverage — the contract in
    providers.py. A provider that throws takes the whole diagnosis down with it
    when one free public service happens to be slow."""
    p = ImperviousProvider()

    def _boom(*args, **kwargs):
        raise ConnectionError("mrlc.gov unreachable")

    monkeypatch.setattr(p, "_fetch_raster", _boom)
    tiles = [_tile("a", WEST, SOUTH, EAST, NORTH)]
    result = p.fetch(tiles)

    assert result.values == {}
    assert result.misses["a"].startswith("nlcd_impervious unavailable")
    assert result.coverage(1) == 0.0


def test_an_empty_batch_is_answered_without_a_request(monkeypatch) -> None:
    p = ImperviousProvider()
    monkeypatch.setattr(
        p, "_fetch_raster",
        lambda *a, **k: pytest.fail("no request should be made for zero tiles"),
    )
    result = p.fetch([])
    assert result.values == {}
    assert result.misses == {}


# ── contract / provenance ────────────────────────────────────────────────────

def test_each_provider_declares_one_field_and_real_provenance() -> None:
    """The Methods page reproduces `source` and `resolution_m` verbatim, so a
    coarse input is never implied to be at tile resolution."""
    for p, field in (
        (ImperviousProvider(), "impervious_pct"),
        (TreeCanopyProvider(), "canopy_pct"),
    ):
        assert p.fields == (field,)
        assert p.info.resolution_m == 30.0
        assert "MRLC" in p.info.source
        assert p.info.vintage


def test_the_year_selects_the_layer() -> None:
    assert ImperviousProvider(year=2019)._layer == "NLCD_2019_Impervious_L48"
    assert TreeCanopyProvider(year=2019)._layer == "nlcd_tcc_conus_2019_v2021-4"
