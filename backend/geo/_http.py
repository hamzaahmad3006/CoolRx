"""Retrying HTTP for the geo providers.

Why this exists
---------------
Every provider here talks to a free public service — mrlc.gov, the USGS 3DEP
ImageServer, api.census.gov, TIGERweb, Overpass. None of them offer an uptime
guarantee, and a full enrichment run hits four of them in sequence, several of
them more than once.

Measured over the Phoenix AOI on 2026-08-21, a single run produced:

* `impervious_pct` empty, while the identical request answered 144/144 tiles when
  issued on its own moments later — mrlc.gov throttling four back-to-back
  requests from the same run;
* `population` empty from an intermittent TLS handshake timeout to
  api.census.gov, which succeeded on five of six later attempts;
* `dist_to_water_m` empty from a read timeout on the 10 km-buffered WCS request.

Each provider already degrades to null-with-a-reason rather than raising, so none
of this crashed anything. That is the correct behaviour for a genuine outage and
the wrong outcome for a blip: the demo silently loses a feature column.

One retry with a short backoff converts most of these blips into answers. It does
not paper over a real outage — after the retries are spent the provider still
degrades exactly as before.

What is retried
---------------
Transport failures (connect/read/TLS timeouts, connection resets) and the
server-side 5xx family, plus 429. A 4xx other than 429 is a request the caller
got wrong, and repeating it unchanged would only waste the deadline.

Redirects are followed. api.census.gov answered 302 to a perfectly ordinary ACS
query during the same investigation, and httpx does not follow redirects by
default — an unfollowed 302 arrives as an empty body and parses as "no data",
which is indistinguishable from a genuine empty result.
"""

from __future__ import annotations

import time
from typing import Any, Final

import httpx
import structlog

log = structlog.get_logger(__name__)

#: Attempts in total, not retries after the first. Three is enough to clear a
#: throttle window without turning one slow service into a stalled job.
DEFAULT_ATTEMPTS: Final[int] = 3

#: Seconds before the second attempt; doubled before each one after that.
DEFAULT_BACKOFF_S: Final[float] = 2.0

#: Status codes worth repeating. 429 is an explicit "slow down", and the 5xx
#: family is the server saying the failure was on its side.
_RETRY_STATUS: Final[frozenset[int]] = frozenset({429, 500, 502, 503, 504})


class _Retryable(Exception):
    """Internal marker: this attempt failed in a way worth repeating."""


def request(
    method: str,
    url: str,
    *,
    attempts: int = DEFAULT_ATTEMPTS,
    backoff_s: float = DEFAULT_BACKOFF_S,
    provider: str = "geo",
    **kwargs: Any,
) -> httpx.Response:
    """Issue a request, retrying transport failures and 429/5xx.

    Follows redirects unless the caller says otherwise. Raises the final
    exception, or returns the final response, once the attempts are spent — the
    caller's own degradation path then takes over unchanged.
    """
    kwargs.setdefault("follow_redirects", True)

    delay = backoff_s
    last_exc: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            response = httpx.request(method, url, **kwargs)
            if response.status_code in _RETRY_STATUS and attempt < attempts:
                log.info(
                    "geo.http_retrying",
                    provider=provider,
                    status=response.status_code,
                    attempt=attempt,
                    sleeping_s=delay,
                )
                raise _Retryable(f"HTTP {response.status_code}")
            return response

        except _Retryable:
            pass

        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_exc = exc
            if attempt >= attempts:
                log.warning(
                    "geo.http_exhausted",
                    provider=provider,
                    error=type(exc).__name__,
                    attempts=attempts,
                )
                raise
            log.info(
                "geo.http_retrying",
                provider=provider,
                error=type(exc).__name__,
                attempt=attempt,
                sleeping_s=delay,
            )

        time.sleep(delay)
        delay *= 2

    # Unreachable: the final iteration either returns the response (a 429/5xx on
    # the last attempt is handed back for the caller to inspect, since
    # `attempt < attempts` is False) or re-raises the transport error.
    raise AssertionError("retry loop exited without returning")  # pragma: no cover


def get(url: str, **kwargs: Any) -> httpx.Response:
    """`request` with method GET."""
    return request("GET", url, **kwargs)


def post(url: str, **kwargs: Any) -> httpx.Response:
    """`request` with method POST."""
    return request("POST", url, **kwargs)
