"""Request-hash cache and fixture resolution.

Two mechanisms, one key:

  request_hash = SHA-256 of the canonically serialised request body

Everything follows from making that key stable — deduplication, credit savings,
provenance, fixture-mode reproducibility, and idempotency when a worker dies
mid-job and the task is retried (SRS FR-003, FR-022).

The canonical form sorts keys and strips whitespace, so two logically identical
requests built in different field orders hash identically. Without that, the
cache would silently miss and every miss would cost credits.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .errors import FixtureMissing


def canonical_json(payload: dict[str, Any]) -> str:
    """Deterministic JSON: sorted keys, no incidental whitespace.

    `sort_keys` is the load-bearing part. Python dict ordering reflects insertion
    order, so the same request assembled in a different field order would
    otherwise produce a different hash and a false cache miss.
    """
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )


def compute_request_hash(endpoint: str, payload: dict[str, Any]) -> str:
    """Stable cache key for a request.

    The endpoint is part of the key: an identical body sent to two endpoints is
    two different requests.
    """
    canonical = f"{endpoint}\n{canonical_json(payload)}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class FixtureStore:
    """Committed FortyGuard responses, keyed by request hash.

    Fixture mode exists so a reviewer can clone the repository and run the whole
    product with no API key and no credits (SRS FR-022). It is also what makes the
    demo unbreakable.

    A miss raises rather than falling through to a live call. Silently reaching
    the network in fixture mode would spend credits and void the reproducibility
    guarantee, which is a worse failure than a loud error.
    """

    def __init__(self, directory: str | Path, *, strict: bool = True) -> None:
        self.directory = Path(directory)
        self.strict = strict

    def path_for(self, request_hash: str) -> Path:
        return self.directory / f"{request_hash}.json"

    def has(self, request_hash: str) -> bool:
        return self.path_for(request_hash).is_file()

    def load(self, request_hash: str, endpoint: str) -> dict[str, Any]:
        path = self.path_for(request_hash)
        if not path.is_file():
            raise FixtureMissing(request_hash, endpoint)

        with path.open("r", encoding="utf-8") as handle:
            data: dict[str, Any] = json.load(handle)
        return data

    def save(
        self,
        request_hash: str,
        endpoint: str,
        request_body: dict[str, Any],
        response: dict[str, Any],
        meta: dict[str, Any] | None = None,
    ) -> Path:
        """Record a live response as a fixture.

        Used by the harvest tooling to build the committed fixture set. The
        request body is stored alongside the response so a reviewer can see what
        produced it — the fixture is documentation as much as test data.
        """
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.path_for(request_hash)
        payload = {
            "request_hash": request_hash,
            "endpoint": endpoint,
            "request_body": request_body,
            "response": response,
        }
        # Provenance: which district and which live task produced this recording.
        # Without it a fixture-backed run has no activity_id to resolve against
        # fg_requests (FR-019), and a grouped holdout cannot tell two districts
        # apart. Merged rather than nested so existing readers of the envelope
        # keep working.
        if meta:
            payload.update(meta)
        with path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, ensure_ascii=False)
        return path

    def total_bytes(self) -> int:
        """Committed fixtures are budgeted at under 25 MB (SRS §12.4)."""
        if not self.directory.is_dir():
            return 0
        return sum(f.stat().st_size for f in self.directory.glob("*.json"))
