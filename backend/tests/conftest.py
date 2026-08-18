"""Session-wide test isolation.

The problem this solves: `core.config.Settings` reads `env_file=".env"`, so a
plain `pytest` run inherits whatever a developer happens to have configured
locally — including a live `FORTYGUARD_API_KEY` and, if `FIXTURE_MODE=false`, a
pipeline that will happily submit real tasks and poll them. A full-suite run in
that state sat for 35 minutes making live calls before it was killed. Tests that
can spend credits are not tests; they are an invoice.

So the environment is pinned here, at import time, before any test module
imports `core.config` and triggers `Settings()`. Doing it in a fixture would be
too late for anything read at module scope.

Two guarantees:

  1. `FIXTURE_MODE=true` — the client resolves cache, then fixture, and never
     reaches the network. `FIXTURE_STRICT=true` keeps a fixture miss loud, so a
     missing recording fails rather than silently falling through to a live call.
  2. `FORTYGUARD_API_KEY=""` — belt and braces. Even if a test forces fixture
     mode off, there is no credential to spend.

`FIXTURE_MODE=true` also means `Settings._check_required_secrets` does not demand
a key, so the suite runs on a machine that has never seen one — which is exactly
what CI does.
"""

from __future__ import annotations

import os

# ── Pinned before any project import. Order matters. ─────────────────────────
# `setdefault` is deliberately NOT used: a stale value in the developer's shell
# is the exact failure mode being prevented, so these overwrite unconditionally.
os.environ["FIXTURE_MODE"] = "true"
os.environ["FIXTURE_STRICT"] = "true"
os.environ["FORTYGUARD_API_KEY"] = ""

# Narration is optional by design (`agent.llm.build_client` returns None without a
# key), so blanking these keeps agent tests deterministic and free rather than
# occasionally billing an LLM provider.
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["GROQ_API_KEY"] = ""
os.environ["LLM_PROVIDER"] = "none"

import pytest  # noqa: E402  — must follow the environment pin above


@pytest.fixture(scope="session", autouse=True)
def _assert_offline() -> None:
    """Fail the run, loudly, if anything re-enabled live calls.

    A guard rather than a comment: if some future fixture flips `FIXTURE_MODE`,
    this turns a silent credit leak into a red test at session start.
    """
    from core.config import get_settings

    settings = get_settings()
    assert settings.fixture_mode is True, (
        "Tests must run in fixture mode. Live FortyGuard calls cost credits and "
        "make the suite non-deterministic."
    )
    assert not settings.fortyguard_api_key, (
        "A FortyGuard API key is visible to the test session. Tests must not be "
        "able to authenticate against the live API."
    )
