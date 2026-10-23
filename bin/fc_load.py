"""The machine-wide load hold: one state file under ~/.compose that every process reads and moves."""
import fcntl, json, os, time
from pathlib import Path

import fc_config


def limits():
    cores = os.cpu_count() or 1
    cfg = fc_config.LOAD
    return {"cores": cores, "high": cfg.get("high", cores * 1.5), "low": cfg.get("low", cores * 1.0), "warn": cfg.get("warn", cores * 1.25)}


def off(force=False):
    return bool(force) or os.environ.get("COMPOSE_NO_LOAD") == "1"


def update(avg=None):
    if avg is None:
        avg = os.getloadavg()[0]
    lim = limits()
    home = Path.home() / ".compose"
    path = home / "load.json"

    def read():
        try:
            return json.loads(path.read_text())
        except FileNotFoundError:
            return {"held": False, "since": None, "n": 0, "log": []}

    kind = "held" if avg > lim["high"] else "released" if avg < lim["low"] else None
    state = read()
    new = []
    if kind and (kind == "held") != state["held"]:
        home.mkdir(parents=True, exist_ok=True)
        with open(home / "load.lock", "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            state = read()
            if (kind == "held") != state["held"]:
                state["n"] += 1
                entry = {"n": state["n"], "at": time.time(), "kind": kind, "avg": float(avg)}
                state["held"] = kind == "held"
                state["since"] = entry["at"] if state["held"] else None
                state["log"] = (state["log"] + [entry])[-50:]
                path.write_text(json.dumps(state))
                new = [entry]
    return {**state, "avg": avg, "new": new}


def held(force=False):
    return False if off(force) else update()["held"]


def since(n):
    path = Path.home() / ".compose" / "load.json"
    try:
        log = json.loads(path.read_text())["log"]
    except FileNotFoundError:
        return []
    return [e for e in log if e["n"] > n]
