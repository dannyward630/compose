"""Harnesses other than Claude Code and pi: one table of them, and the accessors every other module reads it through."""
import json
import os
import shutil
from pathlib import Path

import fc_core


def _codex_probe(cid):
    return ["codex", "exec", "--ephemeral", "--skip-git-repo-check"] + (["-m", cid] if cid else []) + ["Reply with exactly: ok"]

def _codex_result(p):
    if p.returncode == 0:
        return True, "answered"
    for line in p.stderr.splitlines():
        if line.startswith("ERROR: "):
            body = line[len("ERROR: "):]
            try:
                return False, json.loads(body)["error"]["message"]
            except (ValueError, KeyError, TypeError):
                return False, body.strip()
    tail = [l.strip() for l in p.stderr.splitlines() if l.strip()] or [l.strip() for l in p.stdout.splitlines() if l.strip()]
    return False, tail[-1] if tail else f"exit {p.returncode}"

def _git_dirs(f):
    raise NotImplementedError

def _codex_argv(cid, effort, prompt, skill, cwd, results, work=None, more=()):
    raise NotImplementedError

def _codex_events(text):
    raise NotImplementedError

def _codex_once(cid, cwd, prompt, read_only=False):
    raise NotImplementedError

def _codex_hash(event, group):
    raise NotImplementedError

HARNESSES = {
    "codex": {"name": "Codex", "kind": "codex", "exe": "codex", "home_env": "CODEX_HOME", "home": "~/.codex", "sigil": "$",
              "example": "gpt-6.1-sol", "herdr_ready": False, "probe": _codex_probe, "result": _codex_result, "argv": _codex_argv},
    "gemini": {},
    "grok": {},
}

RESERVED = tuple(HARNESSES)


def harness_of(model):
    for key in rows():
        if model == key or (model or "").startswith(key + ":"):
            return key
    return None

def model_id(model):
    key = harness_of(model)
    return (model[len(key) + 1:] or None) if key and model != key else None

def rows():
    return [k for k, v in HARNESSES.items() if v]

def installed():
    return [k for k in rows() if shutil.which(HARNESSES[k]["exe"])]

def home_dir(key):
    raise NotImplementedError

def skills_dir(key):
    row = HARNESSES[key]
    return Path(os.environ.get(row["home_env"]) or os.path.expanduser(row["home"])) / "skills"

def probe_command(model):
    return HARNESSES[harness_of(model)]["probe"](model_id(model))

def probe_result(model, p):
    return HARNESSES[harness_of(model)]["result"](p)

def crew_argv(model, effort, prompt, skill, cwd, results, work=None, more=()):
    raise NotImplementedError

def once_command(model, cwd, prompt, read_only=False):
    raise NotImplementedError

def once_result(model, p):
    raise NotImplementedError

def hook_groups(key, checkout):
    raise NotImplementedError
