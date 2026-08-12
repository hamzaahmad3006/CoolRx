"""Agent trace schemas.

The trace is a product feature, not a debug log. It is the page that answers "did
a language model make up any of these numbers?", so the guard verdict and any
violations are required fields and are shown rather than filtered.

`guard_verdict == "failed"` is a legitimate, displayable state: it means the guard
caught fabricated numerals and the response fell back to the number-free template.
That is the system working, and hiding it would defeat the point of measuring it.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field

from .common import ApiModel

AgentNodeType = Literal["deterministic", "llm"]

#: pass    — no numeral outside the allowed set reached the output
#: retried — a violation was caught and the node was re-run successfully
#: failed  — violations persisted; output fell back to the number-free template
GuardVerdict = Literal["pass", "retried", "failed"]


class AgentNodeRecord(ApiModel):
    name: str
    #: Labelling each node deterministic or llm is what lets a reader see that the
    #: numbers come from the deterministic nodes and only the prose comes from the
    #: model.
    type: AgentNodeType
    duration_ms: int
    #: Null on deterministic nodes, which consume no tokens.
    tokens_in: int | None = None
    tokens_out: int | None = None
    status: Literal["completed", "failed", "skipped"] = "completed"


class GuardViolation(ApiModel):
    """One numeral the guard rejected.

    Both the offending token and the surrounding text are kept: the token alone
    does not show whether the model invented a figure or merely reformatted an
    allowed one, and that distinction is the whole diagnostic value.
    """

    node: str
    token: str
    context: str
    reason: str


class AgentRunResponse(ApiModel):
    id: uuid.UUID
    plan_id: uuid.UUID
    graph_version: str
    model: str
    nodes: list[AgentNodeRecord]
    guard_verdict: GuardVerdict
    #: Empty on a clean run. Populated violations are displayed, not suppressed.
    guard_violations: list[GuardViolation] = Field(default_factory=list)
    tokens_in: int | None = None
    tokens_out: int | None = None
    duration_ms: int | None = None
    created_at: datetime


class NumericGuardReport(ApiModel):
    """Result of one guard pass.

    Returned by the guard itself so the check is inspectable in tests rather than
    only observable through its side effect on the output.
    """

    passed: bool
    #: Numerals the guard was willing to accept, drawn from the structured input.
    allowed_tokens: list[str]
    violations: list[GuardViolation]
    #: True when the output was replaced by the number-free template.
    fell_back: bool = False
