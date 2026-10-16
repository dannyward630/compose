"""Token rows per teammate session and per run provider, their total, and the table `fast-coding cost` prints."""
from __future__ import annotations

from pathlib import Path

import fc_sessions  # noqa: F401


def rows(proj: Path) -> list[dict]:
    raise NotImplementedError("fc_cost.rows")


def total(rows) -> dict:
    raise NotImplementedError("fc_cost.total")


def render(rows) -> str:
    raise NotImplementedError("fc_cost.render")
