"""Stable tile identifiers.

A tile key must name a *place on the ground*, not a position in a result array. If
it named the latter, re-running a diagnosis with a different AOI or a different
analytic would renumber every tile, and the joins between `tiles`, `tile_features`,
`exposure` and `attribution` would silently bind the wrong rows together.

Geohash of the tile centroid gives that property for free: the same ground location
always encodes to the same string, and the encoding is comparable across projects,
runs and analytics.

Precision 9 is used. Its cell is roughly 4.8 m × 4.8 m, comfortably finer than the
60 m minimum tile, so two adjacent tile centroids — 60 m apart at the closest —
never collide into one key. Precision 8 would be 38 m × 19 m, which is *not* safe:
two neighbouring centroids could share a cell along the narrow axis.
"""

from __future__ import annotations

from typing import Final

#: Standard geohash alphabet. Excludes a, i, l and o to avoid transcription errors.
_BASE32: Final[str] = "0123456789bcdefghjkmnpqrstuvwxyz"
_DECODE: Final[dict[str, int]] = {char: index for index, char in enumerate(_BASE32)}

#: 4.8 m × 4.8 m cells — finer than the 60 m minimum tile.
DEFAULT_PRECISION: Final[int] = 9


def encode_geohash(
    longitude: float, latitude: float, precision: int = DEFAULT_PRECISION
) -> str:
    """Encode a coordinate as a geohash.

    Raises on out-of-range input rather than clamping. A latitude of 91° is a bug
    upstream — silently folding it to 90° would produce a plausible key for the
    wrong place.
    """
    if not -180.0 <= longitude <= 180.0:
        raise ValueError(f"longitude {longitude} is outside [-180, 180]")
    if not -90.0 <= latitude <= 90.0:
        raise ValueError(f"latitude {latitude} is outside [-90, 90]")
    if precision < 1:
        raise ValueError(f"precision must be at least 1, got {precision}")

    lon_range = [-180.0, 180.0]
    lat_range = [-90.0, 90.0]

    result: list[str] = []
    bits = 0
    bit_count = 0
    use_longitude = True

    while len(result) < precision:
        if use_longitude:
            midpoint = (lon_range[0] + lon_range[1]) / 2
            if longitude > midpoint:
                bits = (bits << 1) | 1
                lon_range[0] = midpoint
            else:
                bits <<= 1
                lon_range[1] = midpoint
        else:
            midpoint = (lat_range[0] + lat_range[1]) / 2
            if latitude > midpoint:
                bits = (bits << 1) | 1
                lat_range[0] = midpoint
            else:
                bits <<= 1
                lat_range[1] = midpoint

        use_longitude = not use_longitude
        bit_count += 1

        if bit_count == 5:
            result.append(_BASE32[bits])
            bits = 0
            bit_count = 0

    return "".join(result)


def decode_geohash(geohash: str) -> tuple[float, float]:
    """Decode a geohash to the centre of its cell, as `(longitude, latitude)`.

    The centre, not a corner: decoding to a corner then re-encoding could land in
    the neighbouring cell through floating-point drift, breaking the round-trip
    property the tile keys depend on.
    """
    if not geohash:
        raise ValueError("geohash must not be empty")

    lon_range = [-180.0, 180.0]
    lat_range = [-90.0, 90.0]
    use_longitude = True

    for char in geohash.lower():
        try:
            value = _DECODE[char]
        except KeyError:
            raise ValueError(
                f"{char!r} is not a valid geohash character"
            ) from None

        for shift in range(4, -1, -1):
            bit = (value >> shift) & 1
            target = lon_range if use_longitude else lat_range
            midpoint = (target[0] + target[1]) / 2
            if bit:
                target[0] = midpoint
            else:
                target[1] = midpoint
            use_longitude = not use_longitude

    return (
        (lon_range[0] + lon_range[1]) / 2,
        (lat_range[0] + lat_range[1]) / 2,
    )


def tile_key(
    longitude: float, latitude: float, precision: int = DEFAULT_PRECISION
) -> str:
    """The stable key for the tile whose centroid is at this coordinate."""
    return encode_geohash(longitude, latitude, precision)
