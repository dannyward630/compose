"""Claude Code session logs: where a session's log lives, which log is a teammate's, and the tokens it used. Stdlib only."""
from __future__ import annotations

from pathlib import Path


def log_dir(cwd) -> Path:
    raise NotImplementedError("fc_sessions.log_dir")


def usage(path) -> dict:
    raise NotImplementedError("fc_sessions.usage")


def find_session(cwd, started_at, brief_file) -> Path | None:
    raise NotImplementedError("fc_sessions.find_session")
