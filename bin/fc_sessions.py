import hashlib
import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

KEYS = {"input_tokens": "input", "cache_creation_input_tokens": "cache_created",
        "cache_read_input_tokens": "cache_read", "output_tokens": "output"}


def log_dir(cwd):
    slug = "".join(c if c.isascii() and c.isalnum() else "-" for c in str(cwd))
    return Path.home() / ".claude" / "projects" / slug


_cache = {}  # path -> what was read so far: the offset after the last complete line, the ids seen, the running sums


def usage(path):
    """Turns, tokens, and model of a session log. A log is append-only and a live one grows every turn to tens of MB, so
    only the bytes added since the last read are parsed; a log rewritten shorter is read from the start; a line still being
    written (no newline yet) waits for the next read. The read is also kept on disk, so a new process returns an unchanged
    log's result without opening it and continues a grown one from the saved offset."""
    p = Path(path).resolve()
    st = os.stat(p)
    saved = Path.home() / ".compose" / "usage" / (hashlib.sha1(str(p).encode()).hexdigest() + ".json")
    c = _cache.get(str(p))
    if not c:
        try:
            c = json.loads(saved.read_text())
            c = {k: c[k] for k in ("offset", "seen", "model", "turns", "sums", "result", "stat")}
            c["seen"] = set(c["seen"])
            c["stat"] = tuple(c["stat"])
        except (OSError, ValueError, KeyError, TypeError):  # missing, torn, short or the wrong shape: read the log afresh
            c = None
    if c and c["stat"] == (st.st_mtime, st.st_size):
        _cache[str(p)] = c
        return c["result"]
    if not c or st.st_size < c["offset"]:
        c = {"offset": 0, "seen": set(), "model": None, "turns": 0, "sums": dict.fromkeys(KEYS.values(), 0)}
    with open(p, "rb") as f:
        f.seek(c["offset"])
        for line in f:
            if not line.endswith(b"\n"):
                break
            c["offset"] += len(line)
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            msg = obj.get("message")
            if obj.get("type") != "assistant" or not isinstance(msg, dict):
                continue
            mid = msg.get("id")
            if mid in c["seen"]:
                continue
            c["seen"].add(mid)
            c["turns"] += 1
            if c["model"] is None:
                c["model"] = msg.get("model")
            for src, dst in KEYS.items():
                c["sums"][dst] += msg.get("usage", {}).get(src) or 0
    c["result"] = dict(model=c["model"], turns=c["turns"], **c["sums"])
    c["stat"] = (st.st_mtime, st.st_size)
    _cache[str(p)] = c
    tmp = saved.with_name(f"{saved.name}.{os.getpid()}.{threading.get_ident()}.tmp")  # a name of its own: two processes saving at once never meet
    try:
        saved.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps({"offset": c["offset"], "seen": sorted(c["seen"]), "model": c["model"],
                                   "turns": c["turns"], "sums": c["sums"], "result": c["result"], "stat": c["stat"]}))
        os.replace(tmp, saved)
    except OSError:  # the cache is only a shortcut: a save that fails costs the next process one full read
        pass
    return c["result"]


def _first_user(path):
    try:
        with open(path) as f:
            for line in f:
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                if obj.get("type") == "user":
                    return obj
    except OSError:
        pass
    return None


_found = {}


def find_session(cwd, started_at, brief_file):
    """The session log of the teammate started at started_at with brief_file, or None. The directory is read again only when
    a log was added since (its mtime): `status --watch` asks for every teammate every two seconds."""
    d = log_dir(cwd)
    if not d.is_dir():
        return None
    key = (str(d), started_at, str(brief_file))
    stamp = os.stat(d).st_mtime_ns
    hit = _found.get(key)
    if hit and hit[0] == stamp and (hit[1] is None or hit[1].exists()):
        return hit[1]
    best = _find_session(d, started_at, str(brief_file))
    _found[key] = (stamp, best)
    return best


def _find_session(d, started_at, brief):
    start = time.mktime(time.strptime(started_at, "%Y-%m-%d %H:%M:%S")) - 120
    best = None
    for f in d.glob("*.jsonl"):
        line = _first_user(f)
        if line is None:
            continue
        if datetime.strptime(line["timestamp"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc).timestamp() < start:
            continue
        content = line.get("message", {}).get("content")
        if isinstance(content, list):
            content = " ".join(b.get("text", "") for b in content if isinstance(b, dict))
        if isinstance(content, str) and brief in content:
            mt = f.stat().st_mtime
            if best is None or mt > best[0]:
                best = (mt, f)
    return best[1] if best else None
