"""Night mode's record: its limits (an end time and a dollar budget), what the night has spent, the cap that drops to zero when it drains, and its notes."""
from __future__ import annotations
import json, math, subprocess, sys, time
from pathlib import Path

import fc_core, fc_config, fc_factorystate

def until_epoch(hhmm: str, now: float) -> float:
    """The next local HH:MM after `now`: today's if it is still ahead, else tomorrow's."""
    hour, minute = (int(p) for p in hhmm.split(":"))
    t = time.localtime(now)
    at = time.mktime((t.tm_year, t.tm_mon, t.tm_mday, hour, minute, 0, 0, 0, -1))
    if at <= now:
        at = time.mktime((t.tm_year, t.tm_mon, t.tm_mday + 1, hour, minute, 0, 0, 0, -1))
    return at

def new_night(now, until, budget, stop_when) -> dict:
    return {"since": now, "until": until, "budget": budget, "stop_when": stop_when, "draining": None, "ended": None, "stops": 0,
            "spend": 0.0, "wait": None, "asked": {}, "morning": [], "waits": 0, "waited": 0.0}

def night_spend(repo, since) -> float:
    """The cost of every task result written since the night began, over every project."""
    total = 0.0
    for _wt, proj in fc_core.all_projects(repo).values():
        for path in Path(proj, "results").glob("[0-9][0-9][0-9].json"):
            try:
                if path.stat().st_mtime >= since:
                    cost = float(json.loads(path.read_text()).get("cost") or 0)
                    total += cost if math.isfinite(cost) else 0.0
            except (OSError, ValueError, TypeError, AttributeError):
                continue
    return total

def drain_reason(night, now) -> str | None:
    if now >= night["until"]:
        return "morning"
    if night["spend"] >= night["budget"]:
        return "budget"
    return None

def night_cap(state) -> int:
    night = state.get("night")
    if not night or night.get("draining") or night.get("wait") or night.get("ended"):
        return 0
    return fc_config.FACTORY["night_tickets"]

fc_factorystate.PACE["night"] = night_cap

def notes_path(repo) -> Path:
    return fc_core.repo_link(repo).with_name("night-notes.md")

def add_note(repo, line) -> None:
    path = notes_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as out:
        out.write(line.rstrip("\n") + "\n")

def notes_tail(repo, n=8000) -> str:
    try:
        return notes_path(repo).read_text()[-n:]
    except OSError:
        return ""

def spawn_once(repo, args: list[str], log: str) -> int:
    """compose with `args` as a process of its own, out of this session; its output is appended to .compose/<log>. Returns its pid."""
    path = fc_core.repo_link(repo).with_name(log)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as out:
        p = subprocess.Popen([sys.executable, str(Path(__file__).resolve().parent / "compose.py"), *args],
                             start_new_session=True, stdin=subprocess.DEVNULL, stdout=out, stderr=out)
    return p.pid
