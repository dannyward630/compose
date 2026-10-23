"""The machine-wide load hold: one state file under ~/.compose that every process reads and moves."""
import fcntl, json, os, time
from pathlib import Path

import fc_config

WAIT_POLL = 2


def limits():
    cores = os.cpu_count() or 1
    cfg = fc_config.LOAD
    return {"cores": cores, "high": cfg.get("high", cores * 1.5), "low": cfg.get("low", cores * 1.0), "warn": cfg.get("warn", cores * 1.25)}


def off(force=False):
    return bool(force) or os.environ.get("COMPOSE_NO_LOAD") == "1"


def _read(path):
    state = {"held": False, "since": None, "n": 0, "log": [], "warn": False, "claimed": []}
    try:
        state.update(json.loads(path.read_text()))
    except FileNotFoundError:
        pass
    return state


def update(avg=None):
    if avg is None:
        avg = os.getloadavg()[0]
    lim = limits()
    home = Path.home() / ".compose"
    path = home / "load.json"

    def kinds(state):
        out = []
        if avg > lim["high"] and not state["held"]:
            out.append("held")
        elif avg < lim["low"] and state["held"]:
            out.append("released")
        if lim["warn"] <= avg < lim["high"] and not state["warn"]:
            out.append("warn")
        elif avg < lim["low"] and state["warn"]:
            out.append("cleared")
        return out

    state = _read(path)
    new = []
    if kinds(state):
        home.mkdir(parents=True, exist_ok=True)
        with open(home / "load.lock", "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            state = _read(path)
            for kind in kinds(state):
                state["n"] += 1
                entry = {"n": state["n"], "at": time.time(), "kind": kind, "avg": float(avg)}
                if kind in ("held", "released"):
                    state["held"] = kind == "held"
                    state["since"] = entry["at"] if state["held"] else None
                else:
                    state["warn"] = kind == "warn"
                state["log"] = (state["log"] + [entry])[-50:]
                new.append(entry)
            path.write_text(json.dumps(state))
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


def wait(say, force=False):
    if off(force):
        return 0.0
    lim, t0 = limits(), time.time()
    s = update()
    if not s["held"]:
        return 0.0
    say(f"load {s['avg']:.1f} on {lim['cores']} cores is above {lim['high']:.1f}: "
        f"waiting until it falls below {lim['low']:.1f}")
    while True:
        time.sleep(WAIT_POLL)
        if not update()["held"]:
            break
    return time.time() - t0


def claim(n):
    home = Path.home() / ".compose"
    home.mkdir(parents=True, exist_ok=True)
    with open(home / "load.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = home / "load.json"
        state = _read(path)
        if n in state["claimed"]:
            return False
        state["claimed"] = (state["claimed"] + [n])[-50:]
        path.write_text(json.dumps(state))
        return True
