"""The provider chain is wired to the classes that actually exist.

Why this file exists
--------------------
`default_providers` imports every optional provider inside a try/except and
substitutes an `UnavailableProvider` when one cannot be built. That degradation
is deliberate: a national raster service being briefly unwell must not take a
diagnosis down with it.

It is also silent, and on 2026-08-21 it was found to have hidden a real defect
for a week. The factory imported `NlcdProvider` from `geo.landcover` and
`TerrainProvider` from `geo.terrain`. Neither name has ever existed — the classes
are `LandCoverProvider` and `ElevationProvider`. Both imports raised ImportError,
both were swallowed, and every land-cover and terrain feature came back null in
every run. Five further providers were not referenced by the factory at all.

Nothing failed. The suite stayed green, the pipeline completed, and the columns
were null with a named reason, which is exactly what a genuine outage looks like.

These tests close that gap: when a provider's dependencies are present, it must
arrive as itself. A rename, a moved module or a changed constructor signature now
fails here instead of silently emptying the feature layer.
"""

from __future__ import annotations

import pytest

from geo import REQUIRED_FEATURE_FIELDS, default_providers
from geo.providers import UnavailableProvider

#: Providers that must be live whenever their dependencies are importable.
#: Keyed by provider name, valued by the fields it is responsible for.
EXPECTED_LIVE: dict[str, tuple[str, ...]] = {
    "geometry": ("latitude", "hour_utc", "doy"),
    "nlcd_impervious": ("impervious_pct",),
    "nlcd_tree_canopy": ("canopy_pct",),
    "nlcd_land_cover": ("water_pct", "grass_shrub_pct"),
    "osm_building_footprints": ("building_pct",),
    "usgs_3dep_elevation": ("elevation_m", "local_relief_m"),
    "nlcd_water_distance": ("dist_to_water_m",),
    "census_acs_exposure": ("population", "pct_over65"),
    "census_acs_poverty": ("pct_poverty",),
}

#: In REQUIRED_FEATURE_FIELDS but deliberately unsourced. Both feed a predicted
#: temperature reduction a city would spend money on, and neither has a citable
#: source yet, so they are registered as explicitly unavailable rather than
#: filled with a constant. Moving one of these to EXPECTED_LIVE is a deliberate
#: act that should accompany a real source.
EXPECTED_UNAVAILABLE: tuple[str, ...] = ("albedo_proxy", "openness_proxy")

#: Not a provider: derived from the FortyGuard temperature field after
#: enrichment and stamped on by `apply_district_mean`.
SUPPLIED_ELSEWHERE: tuple[str, ...] = ("district_mean_c",)


def _rasterio_present() -> bool:
    try:
        import rasterio  # noqa: F401
        import scipy.ndimage  # noqa: F401
    except ImportError:
        return False
    return True


@pytest.fixture
def chain():
    return default_providers(hour_utc=22, doy=233, census_api_key="test-key")


def _by_name(chain) -> dict:
    return {p.info.name: p for p in chain}


# ── the rename guard ─────────────────────────────────────────────────────────

@pytest.mark.skipif(
    not _rasterio_present(), reason="raster dependencies not installed"
)
@pytest.mark.parametrize("name", sorted(EXPECTED_LIVE))
def test_provider_is_live_not_silently_degraded(chain, name: str) -> None:
    """The regression test for the 2026-08-21 defect.

    A class rename, a moved module or a changed constructor signature turns the
    real provider into an `UnavailableProvider` without raising. This asserts it
    arrived as itself.
    """
    provider = _by_name(chain).get(name)
    assert provider is not None, (
        f"{name!r} is missing from the chain entirely. If it was renamed, update "
        f"EXPECTED_LIVE and default_providers together."
    )
    assert not isinstance(provider, UnavailableProvider), (
        f"{name!r} silently degraded to UnavailableProvider. This is the failure "
        f"mode that emptied the feature layer for a week — usually an ImportError "
        f"from a renamed class, swallowed by the availability try/except."
    )


@pytest.mark.skipif(
    not _rasterio_present(), reason="raster dependencies not installed"
)
def test_no_unexpected_provider_degraded(chain) -> None:
    """Catches a degraded provider whose name is not yet in EXPECTED_LIVE."""
    degraded = {
        p.info.name for p in chain if isinstance(p, UnavailableProvider)
    }
    assert degraded == set(EXPECTED_UNAVAILABLE), (
        f"unexpected degradation: {sorted(degraded - set(EXPECTED_UNAVAILABLE))}"
    )


@pytest.mark.parametrize("name", sorted(EXPECTED_LIVE))
def test_provider_claims_the_fields_it_is_registered_for(chain, name: str) -> None:
    """A provider that loads but claims different fields leaves the originals
    null just as effectively as one that fails to load."""
    provider = _by_name(chain).get(name)
    if provider is None or isinstance(provider, UnavailableProvider):
        pytest.skip(f"{name} unavailable in this environment")
    assert set(provider.fields) == set(EXPECTED_LIVE[name])


# ── coverage of the required feature set ─────────────────────────────────────

def test_every_required_field_is_claimed_by_something(chain) -> None:
    """No field may fall through the chain unclaimed.

    An unclaimed field is worse than a null one: it never appears in the
    enrichment report, so nothing records that it is missing.
    """
    claimed: set[str] = set()
    for provider in chain:
        claimed |= set(provider.fields)

    unclaimed = [
        f
        for f in REQUIRED_FEATURE_FIELDS
        if f not in claimed and f not in SUPPLIED_ELSEWHERE
    ]
    assert not unclaimed, f"required fields claimed by no provider: {unclaimed}"


def test_district_mean_is_not_a_provider(chain) -> None:
    """It is derived from the temperature field after enrichment, not fetched."""
    claimed: set[str] = set()
    for provider in chain:
        claimed |= set(provider.fields)
    assert "district_mean_c" not in claimed


def test_unsourced_fields_are_named_not_omitted(chain) -> None:
    """albedo and openness must appear with a reason, so the enrichment report
    can say why they are null rather than leaving a hole."""
    by_name = _by_name(chain)
    for name in EXPECTED_UNAVAILABLE:
        provider = by_name.get(name)
        assert provider is not None, f"{name} vanished from the chain"
        assert isinstance(provider, UnavailableProvider)
        assert provider.info.name == name


def test_no_two_providers_claim_the_same_field(chain) -> None:
    """`enrich_tiles` lets the first answer win, so a duplicate claim means one
    provider silently shadows another."""
    seen: dict[str, str] = {}
    for provider in chain:
        for field in provider.fields:
            assert field not in seen, (
                f"{field!r} claimed by both {seen[field]!r} and "
                f"{provider.info.name!r}; the second will never be reached"
            )
            seen[field] = provider.info.name


# ── ordering and construction ────────────────────────────────────────────────

def test_geometry_is_first(chain) -> None:
    """It needs no network and no key, so it should never be behind a provider
    that might block on one."""
    assert chain[0].info.name == "geometry"


def test_a_degraded_provider_keeps_the_name_of_the_one_it_replaces() -> None:
    """The stand-in must answer to the same name as the real provider.

    Caught during the 2026-08-21 rewiring: the census stand-in was registered as
    `census_exposure` while the live provider calls itself `census_acs_exposure`.
    The enrichment report and the provenance record name whichever one ran, so a
    mismatch means the Methods page shows a different source name depending on
    whether the key was present — with nothing to indicate the two are the same
    slot.
    """
    live = {p.info.name for p in default_providers(census_api_key="test-key")}
    degraded = {p.info.name for p in default_providers(census_api_key=None)}
    assert live == degraded, (
        f"names differ by availability: only-live={sorted(live - degraded)}, "
        f"only-degraded={sorted(degraded - live)}"
    )


def test_chain_builds_without_a_census_key(chain) -> None:
    """Absent a key the census providers should still be named, so the report can
    say why population is null — the rest of the diagnosis does not depend on it."""
    without = default_providers(hour_utc=22, doy=233, census_api_key=None)
    assert len(without) == len(chain)
    names = {p.info.name for p in without}
    assert "census_acs_exposure" in names
