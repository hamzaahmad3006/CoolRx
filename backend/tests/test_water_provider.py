"""Water-distance provider tests. Offline — the land-cover fetch is stubbed.

Verified live on 2026-08-21 over the Phoenix AOI: 2.82-3.00 km to the nearest open
water, decreasing steadily north-east across the four tiles.

The behaviour worth protecting is that "no water found" is null rather than a large
number. A tile 10 km from water and one 60 km from it would both need a figure this
method cannot produce.
"""

from __future__ import annotations

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_bounds

from geo.grid import Tile
from geo.water import WaterDistanceProvider

WEST, SOUTH, EAST, NORTH = -112.10, 33.44, -112.06, 33.47


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
        dtype="uint8", crs="EPSG:4326",
        transform=from_bounds(WEST, SOUTH, EAST, NORTH, width, height),
    ) as dst:
        dst.write(values, 1)
    ds = memfile.open()
    return ds, ds.read(1)


@pytest.fixture
def provider(monkeypatch):
    def _make(values: np.ndarray):
        p = WaterDistanceProvider()
        monkeypatch.setattr(
            p._land_cover, "_fetch_coverage", lambda *a, **k: _raster(values)
        )
        return p
    return _make


def test_a_tile_on_water_is_zero_from_it(provider):
    p = provider(np.full((20, 20), 11, dtype="uint8"))
    result = p.fetch([_tile("t", -112.09, 33.45, -112.08, 33.46)])
    assert result.values["t"]["dist_to_water_m"] == 0.0


def test_distance_grows_with_separation(provider):
    """Water down the left edge; a tile further right must read further away."""
    values = np.full((40, 40), 24, dtype="uint8")
    values[:, 0:2] = 11
    p = provider(values)
    near = _tile("near", -112.098, 33.45, -112.094, 33.455)
    far = _tile("far", -112.070, 33.45, -112.066, 33.455)
    result = p.fetch([near, far])
    assert (
        result.values["far"]["dist_to_water_m"]
        > result.values["near"]["dist_to_water_m"]
    )


def test_distance_is_reported_in_metres_not_pixels(provider):
    """The AOI is ~3.7 km wide, so a tile at the far edge from water on the near
    edge must read thousands of metres — not tens, which is the pixel count."""
    values = np.full((40, 40), 24, dtype="uint8")
    values[:, 0] = 11
    p = provider(values)
    result = p.fetch([_tile("far", -112.070, 33.45, -112.066, 33.455)])
    assert result.values["far"]["dist_to_water_m"] > 1000.0


def test_no_water_in_the_window_answers_null_not_a_floor(provider):
    """Reporting the search radius as if it were a measurement would put a
    fabricated distance into a feature the model trains on."""
    p = provider(np.full((20, 20), 24, dtype="uint8"))
    result = p.fetch([_tile("t", -112.09, 33.45, -112.08, 33.46)])
    assert result.values["t"]["dist_to_water_m"] is None
    assert "10 km" in result.misses["t"]


def test_perennial_ice_does_not_count_as_water(provider):
    """Class 12 is ice and snow. Consistent with landcover.py, which excludes it
    from water_pct for the same reason."""
    p = provider(np.full((20, 20), 12, dtype="uint8"))
    result = p.fetch([_tile("t", -112.09, 33.45, -112.08, 33.46)])
    assert result.values["t"]["dist_to_water_m"] is None


def test_a_transport_failure_yields_misses_rather_than_raising(monkeypatch):
    p = WaterDistanceProvider()

    def _boom(*a, **k):
        raise ConnectionError("mrlc unreachable")

    monkeypatch.setattr(p._land_cover, "_fetch_coverage", _boom)
    result = p.fetch([_tile("t", -112.09, 33.45, -112.08, 33.46)])
    assert result.values == {}
    assert result.misses["t"].startswith("water distance unavailable")


def test_an_empty_batch_makes_no_request(monkeypatch):
    p = WaterDistanceProvider()
    monkeypatch.setattr(
        p._land_cover, "_fetch_coverage",
        lambda *a, **k: pytest.fail("no request should be made for zero tiles"),
    )
    assert p.fetch([]).values == {}


def test_provenance_states_the_search_radius() -> None:
    """A null means 'none within 10 km', and the Methods page must be able to say
    which radius produced that."""
    info = WaterDistanceProvider().info
    assert "10 km" in info.source
    assert "class 11" in info.source
