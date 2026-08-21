"""The geo layer's retrying HTTP helper.

Written after a full Phoenix enrichment run on 2026-08-21 lost three feature
columns to transient upstream failures — mrlc.gov throttling, an intermittent TLS
handshake timeout to api.census.gov, and a read timeout on the water raster. Each
provider degraded correctly to null-with-a-reason, which is right for a real
outage and wrong for a blip.

The behaviour worth protecting: retry what the server says was its fault, never
retry what the caller got wrong, and follow redirects.
"""

from __future__ import annotations

import httpx
import pytest

from geo import _http


class _Response:
    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code


@pytest.fixture(autouse=True)
def _no_sleeping(monkeypatch):
    """The helper's backoff is real seconds; the tests should not spend them."""
    monkeypatch.setattr(_http.time, "sleep", lambda _s: None)


def _counting(responses):
    """Return a fake httpx.request that plays back `responses` in order.

    An entry that is an exception instance is raised rather than returned.
    """
    calls = {"n": 0}

    def _request(method, url, **kwargs):
        item = responses[min(calls["n"], len(responses) - 1)]
        calls["n"] += 1
        if isinstance(item, Exception):
            raise item
        return item

    return _request, calls


# ── what gets retried ────────────────────────────────────────────────────────

@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_server_side_failures_are_retried(monkeypatch, status: int) -> None:
    """429 is an explicit 'slow down' and 5xx is the server saying the fault was
    its own. Both are worth repeating."""
    request, calls = _counting([_Response(status), _Response(200)])
    monkeypatch.setattr(httpx, "request", request)

    response = _http.get("https://example.test/x")
    assert response.status_code == 200
    assert calls["n"] == 2


@pytest.mark.parametrize(
    "exc",
    [
        httpx.ConnectTimeout("handshake timed out"),
        httpx.ReadTimeout("read timed out"),
        httpx.ConnectError("connection refused"),
    ],
)
def test_transport_failures_are_retried(monkeypatch, exc: Exception) -> None:
    """These are the exact failures observed against api.census.gov and the
    10 km-buffered water raster."""
    request, calls = _counting([exc, _Response(200)])
    monkeypatch.setattr(httpx, "request", request)

    assert _http.get("https://example.test/x").status_code == 200
    assert calls["n"] == 2


# ── what does not ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("status", [400, 401, 403, 404, 406, 422])
def test_client_errors_are_not_retried(monkeypatch, status: int) -> None:
    """A 4xx other than 429 is a request the caller got wrong. Repeating it
    unchanged only spends the deadline — Overpass answering 406 to a bad user
    agent would have been retried three times for nothing."""
    request, calls = _counting([_Response(status)])
    monkeypatch.setattr(httpx, "request", request)

    assert _http.get("https://example.test/x").status_code == status
    assert calls["n"] == 1


def test_a_success_makes_exactly_one_request(monkeypatch) -> None:
    request, calls = _counting([_Response(200)])
    monkeypatch.setattr(httpx, "request", request)

    _http.get("https://example.test/x")
    assert calls["n"] == 1


# ── exhaustion hands control back to the provider ────────────────────────────

def test_a_persistent_transport_failure_still_raises(monkeypatch) -> None:
    """After the retries are spent the provider's own degradation path must take
    over unchanged — a real outage still produces null-with-a-reason."""
    request, calls = _counting([httpx.ConnectTimeout("down")])
    monkeypatch.setattr(httpx, "request", request)

    with pytest.raises(httpx.ConnectTimeout):
        _http.get("https://example.test/x")
    assert calls["n"] == _http.DEFAULT_ATTEMPTS


def test_a_persistent_server_error_is_returned_not_raised(monkeypatch) -> None:
    """The caller gets a real response to inspect. Providers check status codes
    and turn them into named reasons; an exception would be reported as a
    transport failure instead, which is a different and less accurate story."""
    request, calls = _counting([_Response(503)])
    monkeypatch.setattr(httpx, "request", request)

    assert _http.get("https://example.test/x").status_code == 503
    assert calls["n"] == _http.DEFAULT_ATTEMPTS


def test_attempts_are_configurable(monkeypatch) -> None:
    request, calls = _counting([httpx.ReadTimeout("slow")])
    monkeypatch.setattr(httpx, "request", request)

    with pytest.raises(httpx.ReadTimeout):
        _http.get("https://example.test/x", attempts=5)
    assert calls["n"] == 5


# ── redirects ────────────────────────────────────────────────────────────────

def test_redirects_are_followed_by_default(monkeypatch) -> None:
    """api.census.gov answered 302 to an ordinary ACS query. httpx does not
    follow redirects by default, and an unfollowed 302 arrives as an empty body
    that parses as 'no data' — indistinguishable from a genuine empty result."""
    seen: dict = {}

    def _request(method, url, **kwargs):
        seen.update(kwargs)
        return _Response(200)

    monkeypatch.setattr(httpx, "request", _request)
    _http.get("https://example.test/x")
    assert seen["follow_redirects"] is True


def test_a_caller_can_opt_out_of_redirects(monkeypatch) -> None:
    seen: dict = {}

    def _request(method, url, **kwargs):
        seen.update(kwargs)
        return _Response(200)

    monkeypatch.setattr(httpx, "request", _request)
    _http.get("https://example.test/x", follow_redirects=False)
    assert seen["follow_redirects"] is False


# ── the method wrappers ──────────────────────────────────────────────────────

@pytest.mark.parametrize(
    ("fn", "expected"), [(_http.get, "GET"), (_http.post, "POST")]
)
def test_method_wrappers_pass_the_right_verb(monkeypatch, fn, expected) -> None:
    seen: dict = {}

    def _request(method, url, **kwargs):
        seen["method"] = method
        return _Response(200)

    monkeypatch.setattr(httpx, "request", _request)
    fn("https://example.test/x")
    assert seen["method"] == expected


def test_caller_kwargs_reach_httpx(monkeypatch) -> None:
    """Providers pass params, headers, timeouts and a body through this helper;
    dropping any of them would silently change the request."""
    seen: dict = {}

    def _request(method, url, **kwargs):
        seen.update(kwargs)
        return _Response(200)

    monkeypatch.setattr(httpx, "request", _request)
    _http.post(
        "https://example.test/x",
        params={"a": "1"},
        headers={"User-Agent": "CoolRx/1.0"},
        timeout=90.0,
        data="query",
    )
    assert seen["params"] == {"a": "1"}
    assert seen["headers"]["User-Agent"] == "CoolRx/1.0"
    assert seen["timeout"] == 90.0
    assert seen["data"] == "query"
