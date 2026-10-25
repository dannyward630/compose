"""Night mode's record: its limits (an end time and a dollar budget), what the night has spent, the cap that drops to zero when it drains, and its notes."""
from __future__ import annotations
import json, math, re, subprocess, sys, time
from pathlib import Path

import fc_core, fc_config, fc_factorystate, fc_factoryturn, fc_models, fc_plan, fc_stall, fc_tasks

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

def unmerged_depth(plan, feature, seen=()) -> int:
    """How many verified-but-unmerged (In Review) levels the feature sits on: 0 with none, else 1 plus the deepest such blocker's own depth."""
    seen = {*seen, feature}
    deeper = [b for b in (plan["features"].get(feature) or {}).get("blockers") or []
              if fc_plan.base_built(b["state"], b.get("labels") or []) and not fc_tasks.blocker_finished(b["state"], b.get("labels") or [])]
    return 1 + max((unmerged_depth(plan, b["id"], seen) for b in deeper if b["id"] not in seen), default=0) if deeper else 0

def one_level(plan, entries, state) -> list:
    """At night, only stories at most one unmerged level deep, plus those already in flight."""
    live = set(fc_factoryturn.in_flight(plan, state))
    return [e for e in entries if e["id"] in live or unmerged_depth(plan, e["feature"]) <= 1]

fc_factoryturn.ORDER_FILTER["night"] = one_level

RESUME_BUFFER = 60  # seconds past a stated reset before the leads are told to carry on
MIN_WAIT = 60  # seconds of the first wait when a limit line states no reset
MAX_FALLBACK = 1800  # the longest such wait
CONTINUE = "night: the usage window has reset; carry on from where you stopped."
IN_HOURS = re.compile(r"\bin (\d+)\s*h(?:ours?)?(?:\s*(\d+)\s*m)?", re.I)
IN_MINUTES = re.compile(r"\bin (\d+)\s*m(?:in(?:utes)?)?\b", re.I)
AT_AMPM = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*([ap]m)\b", re.I)
AT_CLOCK = re.compile(r"\b(\d{1,2}):(\d{2})\b")

def reset_at(line, now) -> float | None:
    """When the usage window a limit line names resets (plus RESUME_BUFFER), else None."""
    m = IN_HOURS.search(line)
    if m:
        return now + int(m.group(1)) * 3600 + int(m.group(2) or 0) * 60 + RESUME_BUFFER
    m = IN_MINUTES.search(line)
    if m:
        return now + int(m.group(1)) * 60 + RESUME_BUFFER
    m = AT_AMPM.search(line)
    if m:
        hour = int(m.group(1)) % 12 + (12 if m.group(3).lower() == "pm" else 0)
        return until_epoch(f"{hour}:{m.group(2) or '00'}", now) + RESUME_BUFFER
    m = AT_CLOCK.search(line)
    if m and int(m.group(1)) < 24 and int(m.group(2)) < 60:
        return until_epoch(f"{m.group(1)}:{m.group(2)}", now) + RESUME_BUFFER
    return None

def fallback_wait(n) -> float:
    return min(MIN_WAIT * 2 ** (n - 1), MAX_FALLBACK)

def no_credit(repo, since) -> str | None:
    """Why the night must end now: a project halted on a payment since it began, else None."""
    for slug, (_wt, proj) in sorted(fc_core.all_projects(repo).items()):
        path = Path(proj, "results", "resume.json")
        try:
            if path.stat().st_mtime >= since:
                return f"{slug}: payment halt ({json.loads(path.read_text()).get('provider') or 'unknown'})"
        except (OSError, ValueError, AttributeError):
            continue
    return None

def usage_step(night, leads, now, read, prompt) -> list[str]:
    """One look at the team leads' panes. A billing line ends the night; a limit line starts or extends a wait; a due wait with no limit left prompts the leads to continue."""
    wait = night.get("wait")
    if wait and now < wait["until"]:
        return []
    limited = {}
    for name in sorted(leads.values()):
        pane = read(name) or ""
        pay = next((ln.strip()[:160] for ln in reversed(pane.strip().splitlines()[-8:]) if fc_models.PAY_RE.search(ln)), None)
        if pay:
            night["ended"] = {"state": "no-credit", "at": now, "why": pay}
            return [f'event factory=night-ended state=no-credit why="{pay}"  (a provider says there is no credit, which is the product owner\'s call: send one PushNotification naming it)']
        line = fc_stall.limit_line(pane)
        if line:
            limited[name] = line
    if limited:
        names = sorted(limited)
        parsed = [t for t in (reset_at(ln, now) for ln in limited.values()) if t]
        n = 0 if parsed else (wait["n"] if wait else 0) + 1
        until = max(parsed) if parsed else now + fallback_wait(n)
        night["wait"] = {"until": until, "n": n, "since": wait["since"] if wait else now, "agents": names}
        line = limited[names[-1]].replace('"', "'")
        return [f'event factory=usage-wait until={time.strftime("%H:%M", time.localtime(until))} agents={",".join(names)} line="{line}"  (a usage window is exhausted: nothing new starts until it resets)']
    if not wait:
        return []
    for name in wait["agents"]:
        prompt(name, CONTINUE)
    night["waits"] += 1
    night["waited"] += now - wait["since"]
    night["wait"] = None
    return [f'event factory=usage-resumed agents={",".join(wait["agents"])}  (the window reset: each waiting team lead was told to continue)']
