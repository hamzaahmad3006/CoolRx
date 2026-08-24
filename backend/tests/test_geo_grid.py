"""Tests for tiling and tile keys.

These target the failures that produce plausible-looking wrong answers rather than
crashes: a grid whose cells are not the requested size, a key that changes between
runs, or an enrichment merge that turns a missing reading into a zero.
"""

from __future__ import annotations

import math

import pytest
from pyproj import Geod

from geo.enrich import apply_district_mean, enrich_tiles
from geo.grid import (
    MAX_TILES,
    Tile,
    build_grid,
    estimate_tile_count,
    utm_epsg_for,
)
from geo.providers import (
    ENRICHABLE_FIELDS,
    FeatureProvider,
    GeometryProvider,
    ProviderInfo,
    ProviderResult,
    UnavailableProvider,
)
from geo.tilekey import decode_geohash, encode_geohash, tile_key

GEOD = Geod(ellps="WGS84")

#: A small central-Phoenix box, well inside the plan cap.
PHOENIX = {"west": -112.10, "south": 33.43, "east": -112.07, "north": 33.455}


# ═════════════════════════════════════════════════════════════════════════════
# Geohash / tile keys
# ═════════════════════════════════════════════════════════════════════════════


def test_geohash_matches_the_known_reference_value() -> None:
    """The canonical geohash example, so the implementation is verifiably standard."""
    assert encode_geohash(-5.6, 42.6, precision=5) == "ezs42"


def test_encode_decode_round_trips_within_cell_size() -> None:
    lon, lat = -112.074, 33.448
    decoded_lon, decoded_lat = decode_geohash(encode_geohash(lon, lat))
    # Precision 9 cells are ~4.8 m; the decoded centre is within half of that.
    assert abs(decoded_lon - lon) < 0.0001
    assert abs(decoded_lat - lat) < 0.0001


def test_same_coordinate_always_yields_the_same_key() -> None:
    """The property every cross-table join depends on."""
    assert tile_key(-112.074, 33.448) == tile_key(-112.074, 33.448)


def test_neighbouring_tile_centroids_do_not_collide() -> None:
    """60 m apart is the closest two centroids ever get; keys must still differ.

    This is why precision 9 is used. At precision 8 the cell is 38 m x 19 m and two
    neighbours could share one key along the narrow axis, silently merging two
    places into one row.
    """
    base_lon, base_lat = -112.074, 33.448
    # ~60 m north and ~60 m east.
    north = tile_key(base_lon, base_lat + 60 / 111_320)
    east = tile_key(
        base_lon + 60 / (111_320 * math.cos(math.radians(base_lat))), base_lat
    )
    origin = tile_key(base_lon, base_lat)
    assert len({origin, north, east}) == 3


@pytest.mark.parametrize(
    ("lon", "lat"),
    [(181.0, 0.0), (-181.0, 0.0), (0.0, 91.0), (0.0, -91.0)],
)
def test_out_of_range_coordinates_raise(lon: float, lat: float) -> None:
    """Clamping would produce a valid-looking key for the wrong place."""
    with pytest.raises(ValueError):
        encode_geohash(lon, lat)


def test_invalid_geohash_character_raises() -> None:
    # 'a' is deliberately absent from the geohash alphabet.
    with pytest.raises(ValueError, match="not a valid geohash"):
        decode_geohash("9qa")


def test_empty_geohash_raises() -> None:
    with pytest.raises(ValueError):
        decode_geohash("")


# ═════════════════════════════════════════════════════════════════════════════
# UTM zone selection
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    ("lon", "lat", "epsg"),
    [
        (-112.07, 33.45, 32612),  # Phoenix, zone 12N
        (-74.0, 40.7, 32618),  # New York, zone 18N
        (-157.8, 21.3, 32604),  # Honolulu, zone 4N
        (-149.9, 61.2, 32606),  # Anchorage, zone 6N
        (-58.4, -34.6, 32721),  # Buenos Aires, zone 21S
        (0.0, 51.5, 32631),  # Greenwich, zone 31N
    ],
)
def test_utm_zone_selection(lon: float, lat: float, epsg: int) -> None:
    assert utm_epsg_for(lon, lat) == epsg


def test_longitude_180_stays_in_zone_60() -> None:
    """The naive formula yields zone 61, which does not exist."""
    assert utm_epsg_for(180.0, 0.0) == 32660


def test_southern_hemisphere_uses_the_327xx_band() -> None:
    assert utm_epsg_for(-58.4, -0.001) >= 32700


# ═════════════════════════════════════════════════════════════════════════════
# Grid geometry
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("granularity", [60, 80, 100])
def test_cells_are_the_requested_size_on_the_ground(granularity: int) -> None:
    """The reason the grid is built in UTM rather than in degrees.

    A degree-based grid produces cells whose width varies with latitude, so
    person-heat-hours would be summed over cells of unequal area. Measured
    geodesically, each cell must be the requested size within a small tolerance.
    """
    tiles, _ = build_grid(**PHOENIX, granularity_m=granularity)
    sample = tiles[len(tiles) // 2]

    _, _, width_m = GEOD.inv(
        sample.west, sample.centroid_lat, sample.east, sample.centroid_lat
    )
    _, _, height_m = GEOD.inv(
        sample.centroid_lon, sample.south, sample.centroid_lon, sample.north
    )

    # 2% tolerance absorbs the UTM square being a slightly rotated quadrilateral
    # in degrees, which widens the degree-extent bounding box a little.
    assert width_m == pytest.approx(granularity, rel=0.02)
    assert height_m == pytest.approx(granularity, rel=0.02)


@pytest.mark.parametrize("granularity", [60, 80, 100])
def test_grid_covers_the_whole_bounding_box(granularity: int) -> None:
    """Snapping extends outward; it must never clip the requested area."""
    tiles, _ = build_grid(**PHOENIX, granularity_m=granularity)
    assert min(t.west for t in tiles) <= PHOENIX["west"]
    assert min(t.south for t in tiles) <= PHOENIX["south"]
    assert max(t.east for t in tiles) >= PHOENIX["east"]
    assert max(t.north for t in tiles) >= PHOENIX["north"]


def test_tile_keys_are_unique_within_a_grid() -> None:
    """A duplicate key would silently merge two places into one row."""
    tiles, spec = build_grid(**PHOENIX, granularity_m=60)
    keys = [t.tile_key for t in tiles]
    assert len(set(keys)) == len(keys) == spec.tile_count


def test_grid_is_deterministic_across_calls() -> None:
    first, _ = build_grid(**PHOENIX, granularity_m=80)
    second, _ = build_grid(**PHOENIX, granularity_m=80)
    assert [t.tile_key for t in first] == [t.tile_key for t in second]


def test_overlapping_aois_share_keys_for_shared_ground() -> None:
    """The payoff of snapping the grid to a global UTM origin.

    Two projects covering overlapping ground must agree on tile keys, so
    `tile_features` and `exposure` can be reused rather than recomputed per AOI. A
    grid anchored on each AOI's own corner would produce two disjoint key sets for
    the same streets.
    """
    a, _ = build_grid(**PHOENIX, granularity_m=60)
    shifted = {
        "west": PHOENIX["west"] + 0.004,
        "south": PHOENIX["south"] + 0.003,
        "east": PHOENIX["east"] + 0.004,
        "north": PHOENIX["north"] + 0.003,
    }
    b, _ = build_grid(**shifted, granularity_m=60)

    shared = {t.tile_key for t in a} & {t.tile_key for t in b}
    assert len(shared) > 100, "overlapping AOIs must share the ground they overlap on"


def test_finer_granularity_yields_more_tiles() -> None:
    counts = {
        granularity: build_grid(**PHOENIX, granularity_m=granularity)[1].tile_count
        for granularity in (60, 80, 100)
    }
    assert counts[60] > counts[80] > counts[100]


def test_estimate_matches_the_built_grid() -> None:
    """The AOI Studio's pre-flight count must equal what the pipeline builds."""
    for granularity in (60, 80, 100):
        _, spec = build_grid(**PHOENIX, granularity_m=granularity)
        assert (
            estimate_tile_count(**PHOENIX, granularity_m=granularity) == spec.tile_count
        )


def test_phoenix_tile_count_is_the_expected_order_of_magnitude() -> None:
    """~3 mi² at 60 m is roughly 2,100 tiles. Guards against an off-by-1000."""
    _, spec = build_grid(**PHOENIX, granularity_m=60)
    assert 1_500 < spec.tile_count < 3_000


def test_spec_reports_the_utm_zone_used() -> None:
    _, spec = build_grid(**PHOENIX, granularity_m=60)
    assert spec.utm_epsg == 32612
    assert spec.spans_utm_zones is False


def test_zone_spanning_aoi_is_flagged_not_rejected() -> None:
    """At district scale the distortion is negligible, but it must be recorded."""
    _, spec = build_grid(
        west=-120.05, south=37.0, east=-119.95, north=37.03, granularity_m=100
    )
    assert spec.spans_utm_zones is True


# ═════════════════════════════════════════════════════════════════════════════
# Grid guards
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("granularity", [30, 50, 90, 120, 0, -60])
def test_invalid_granularity_is_rejected(granularity: int) -> None:
    with pytest.raises(ValueError, match="granularity"):
        build_grid(**PHOENIX, granularity_m=granularity)


def test_inverted_bounds_are_rejected() -> None:
    with pytest.raises(ValueError, match="west"):
        build_grid(
            west=-112.0, south=33.43, east=-112.10, north=33.455, granularity_m=60
        )
    with pytest.raises(ValueError, match="south"):
        build_grid(
            west=-112.10, south=33.50, east=-112.07, north=33.43, granularity_m=60
        )


def test_absurdly_large_grid_is_refused() -> None:
    """A malformed bounding box must not try to allocate millions of rows."""
    with pytest.raises(ValueError, match="ceiling"):
        build_grid(west=-120.0, south=30.0, east=-110.0, north=40.0, granularity_m=60)
    assert MAX_TILES > 7_200, "the ceiling must still allow a full 10 mi² run at 60 m"


# ═════════════════════════════════════════════════════════════════════════════
# Enrichment merge
# ═════════════════════════════════════════════════════════════════════════════


class _StubProvider(FeatureProvider):
    def __init__(
        self,
        name: str,
        values: dict[str, dict[str, float | None]],
        fields: tuple[str, ...],
    ) -> None:
        self._name = name
        self._values = values
        self._fields = fields

    @property
    def info(self) -> ProviderInfo:
        return ProviderInfo(
            name=self._name, resolution_m=30.0, source="stub", vintage="test"
        )

    @property
    def fields(self) -> tuple[str, ...]:
        return self._fields

    def fetch(self, tiles: list[Tile]) -> ProviderResult:
        return ProviderResult(info=self.info, values=dict(self._values))


def _tiles(count: int = 3) -> list[Tile]:
    return [
        Tile(
            tile_key=f"key{i}",
            west=-112.1,
            south=33.4,
            east=-112.0,
            north=33.5,
            centroid_lon=-112.05,
            centroid_lat=33.45,
        )
        for i in range(count)
    ]


def test_every_row_has_every_required_field() -> None:
    """A missing key would let downstream code default the field into existence.

    The row carries the exposure fields as well as the model's inputs. They are
    not model features -- population answers who is exposed, not how hot a tile
    is -- but they are columns on the same row, and seeding them here is what
    stops `enrich_tiles` from dropping a census answer it never made space for.
    """
    rows, _ = enrich_tiles(_tiles(), [GeometryProvider(hour_utc=22, doy=196)])
    for row in rows:
        assert set(row) == {"tile_key", *ENRICHABLE_FIELDS}


def test_unavailable_provider_yields_nulls_not_zeros() -> None:
    """The core rule: no data must never look like a measurement of zero."""
    provider = UnavailableProvider(
        name="nlcd", fields=("canopy_pct", "impervious_pct"), reason="raster missing"
    )
    rows, report = enrich_tiles(_tiles(), [provider])

    for row in rows:
        assert row["canopy_pct"] is None
        assert row["impervious_pct"] is None
    assert "nlcd" in report.unavailable
    assert "canopy_pct" in report.fully_null_fields


def test_a_null_never_overwrites_a_real_value() -> None:
    """Provider ordering must not let a later miss erase an earlier reading."""
    good = _StubProvider("fine", {"key0": {"canopy_pct": 42.0}}, ("canopy_pct",))
    empty = _StubProvider("coarse", {"key0": {"canopy_pct": None}}, ("canopy_pct",))
    rows, _ = enrich_tiles(_tiles(1), [good, empty])
    assert rows[0]["canopy_pct"] == 42.0


def test_first_provider_wins_for_a_shared_field() -> None:
    """A coarse fallback must not overwrite a fine-grained source."""
    fine = _StubProvider("fine", {"key0": {"canopy_pct": 42.0}}, ("canopy_pct",))
    coarse = _StubProvider("coarse", {"key0": {"canopy_pct": 10.0}}, ("canopy_pct",))
    rows, _ = enrich_tiles(_tiles(1), [fine, coarse])
    assert rows[0]["canopy_pct"] == 42.0


def test_partial_coverage_is_measured() -> None:
    """A 40%-covered layer is usable, but the UI has to be able to say so."""
    partial = _StubProvider(
        "partial",
        {"key0": {"canopy_pct": 12.0}, "key1": {"canopy_pct": None}},
        ("canopy_pct",),
    )
    _, report = enrich_tiles(_tiles(4), [partial])
    assert report.coverage_of("canopy_pct") == pytest.approx(0.25)


def test_provider_answering_for_an_unknown_tile_is_ignored() -> None:
    stray = _StubProvider(
        "stray", {"not-in-batch": {"canopy_pct": 99.0}}, ("canopy_pct",)
    )
    rows, _ = enrich_tiles(_tiles(2), [stray])
    assert all(row["canopy_pct"] is None for row in rows)
    assert len(rows) == 2


def test_empty_tile_list_is_handled() -> None:
    rows, report = enrich_tiles([], [GeometryProvider()])
    assert rows == []
    assert report.tile_count == 0


def test_geometry_provider_always_supplies_latitude() -> None:
    """Latitude is a model feature and is never missing."""
    rows, _ = enrich_tiles(_tiles(2), [GeometryProvider(hour_utc=15, doy=200)])
    for row in rows:
        assert row["latitude"] == pytest.approx(33.45)
        assert row["hour_utc"] == 15.0
        assert row["doy"] == 200.0


def test_district_mean_of_none_leaves_the_column_null() -> None:
    """A district mean of 0 °C would make every tile look extraordinarily hot."""
    rows, _ = enrich_tiles(_tiles(2), [GeometryProvider()])
    apply_district_mean(rows, None)
    assert all(row["district_mean_c"] is None for row in rows)

    apply_district_mean(rows, 41.2)
    assert all(row["district_mean_c"] == 41.2 for row in rows)


def test_report_lists_each_provider() -> None:
    rows, report = enrich_tiles(
        _tiles(2),
        [
            GeometryProvider(),
            UnavailableProvider(
                name="nlcd", fields=("canopy_pct",), reason="no raster"
            ),
        ],
    )
    names = {info.name for info in report.providers}
    assert names == {"geometry", "nlcd"}
    assert len(rows) == 2
