import json, os, time
from pathlib import Path


def _dir():
    return Path.home() / ".compose" / "started"


def record(pid, kind, project, waiter=None, until=None, cwd=None):
    d = _dir()
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / f"{pid}.json.tmp"
    tmp.write_text(json.dumps({"pid": pid, "kind": kind, "project": project, "waiter": waiter, "until": until, "cwd": cwd, "at": time.time()}))
    os.replace(tmp, d / f"{pid}.json")


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def entries():
    out = []
    for f in _dir().glob("*.json"):
        try:
            e = json.loads(f.read_text())
            e["alive"] = _alive(e["pid"])
        except (OSError, ValueError, KeyError, TypeError):
            continue
        out.append(e)
    return sorted(out, key=lambda e: e["at"])


def forget(pid):
    try:
        (_dir() / f"{pid}.json").unlink()
    except OSError:
        pass
