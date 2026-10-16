import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

KEYS = {"input_tokens": "input", "cache_creation_input_tokens": "cache_created",
        "cache_read_input_tokens": "cache_read", "output_tokens": "output"}


def log_dir(cwd):
    slug = "".join(c if c.isascii() and c.isalnum() else "-" for c in str(cwd))
    return Path.home() / ".claude" / "projects" / slug


_cache = {}


def usage(path):
    p = Path(path).resolve()
    st = os.stat(p)
    hit = _cache.get(str(p))
    if hit and hit[0] == st.st_mtime and hit[1] == st.st_size:
        return hit[2]
    sums = dict.fromkeys(KEYS.values(), 0)
    model, turns = None, 0
    seen = set()
    with open(p) as f:
        for line in f:
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            msg = obj.get("message")
            if obj.get("type") != "assistant" or not isinstance(msg, dict):
                continue
            mid = msg.get("id")
            if mid in seen:
                continue
            seen.add(mid)
            turns += 1
            if model is None:
                model = msg.get("model")
            for src, dst in KEYS.items():
                sums[dst] += msg.get("usage", {}).get(src) or 0
    result = dict(model=model, turns=turns, **sums)
    _cache[str(p)] = (st.st_mtime, st.st_size, result)
    return result


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


def find_session(cwd, started_at, brief_file):
    d = log_dir(cwd)
    if not d.is_dir():
        return None
    start = time.mktime(time.strptime(started_at, "%Y-%m-%d %H:%M:%S")) - 120
    brief = str(brief_file)
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
