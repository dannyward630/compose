import json
from pathlib import Path

import fc_sessions

FIELDS = ("turns", "input", "cache_created", "cache_read", "output")


def rows(proj: Path, runs=()) -> list[dict]:
    """The teammate sessions, then the run providers. `runs` are the project's run-end lines of the run history: when there are
    any, the providers total every run (run-cost.json holds only the latest); else run-cost.json is read."""
    proj = Path(proj)
    out = []
    crew = proj / "results" / "crew"
    records = []
    for f in sorted(crew.glob("*.json")) if crew.is_dir() else []:
        try:
            c = json.loads(f.read_text())
        except ValueError:
            continue
        if isinstance(c, dict) and "role" in c:
            records.append(c)
    records.sort(key=lambda c: c.get("started_at", ""))
    for c in records:
        row = {"name": c["name"], "role": c["role"], "model": c.get("model", ""),
               **dict.fromkeys(FIELDS, None), "note": "no session log"}
        brief = crew / (c["name"] + ".brief.md")
        log = fc_sessions.find_session(c.get("cwd"), c["started_at"], brief)
        if log:
            u = fc_sessions.usage(log)
            row.update({k: u[k] for k in FIELDS})
            row["model"] = u["model"] or row["model"]
            row["note"] = ""
        out.append(row)
    if runs:
        total_by = {}
        for r in runs:
            for name, v in (r.get("providers") or {}).items():
                t = total_by.setdefault(name, {"calls": 0, "tokens_in": 0, "tokens_out": 0, "runs": 0})
                t["runs"] += 1
                for k in ("calls", "tokens_in", "tokens_out"):
                    t[k] += v.get(k) or 0
        for name, v in sorted(total_by.items()):
            out.append({"name": name, "role": "run", "model": "", "turns": v["calls"], "input": v["tokens_in"], "cache_created": 0,
                        "cache_read": 0, "output": v["tokens_out"], "note": f"{v['runs']} runs"})
    rc = proj / "results" / "run-cost.json"
    if rc.exists() and not runs:
        try:
            run = json.loads(rc.read_text())
        except ValueError:
            run = {}
        for name, v in sorted(run.items()):
            if name == "total" or not isinstance(v, dict):
                continue
            out.append({"name": name, "role": "run", "model": "", "turns": v.get("calls"),
                        "input": v.get("tokens_in"), "cache_created": 0, "cache_read": 0,
                        "output": v.get("tokens_out"), "note": ""})
    return out


def total(rows) -> dict:
    t = {k: sum(r[k] or 0 for r in rows) for k in FIELDS}
    t["teammates"] = sum(1 for r in rows if r["role"] != "run")
    return t


def render(rows) -> str:
    if not rows:
        return "cost  none"
    head = {"name": "name", "role": "role", "model": "model", "turns": "turns", "input": "input",
            "cache_created": "cache created", "cache_read": "cache read", "output": "output", "note": "note"}
    t = total(rows)
    tot = {"name": "total", "role": "", "model": "", "note": "", **t,
           "cache_created": t["cache_created"], "cache_read": t["cache_read"]}
    w = {k: max(len(str(head[k])), *(len(fmt(r[k])) for r in [*rows, tot])) for k in head}
    lines = ["  ".join(str(head[k]).ljust(w[k]) for k in head).rstrip()]
    for r in rows:
        lines.append("  ".join(fmt(r[k]).ljust(w[k]) for k in head).rstrip())
    lines.append("  ".join(fmt(tot[k]).ljust(w[k]) for k in head).rstrip())
    return "\n".join(lines)


def fmt(v):
    if v is None:
        return "-"
    return str(v)
