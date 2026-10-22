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
    p = fc_core.sh(["git", "rev-parse", "--path-format=absolute", "--git-common-dir", "--absolute-git-dir"], f, check=False) if Path(f).is_dir() else None
    return [Path(l).resolve() for l in p.stdout.splitlines()[:2]] if p and p.returncode == 0 else []

def _codex_argv(cid, effort, prompt, skill, cwd, results, work=None, more=()):
    argv = []
    if cid is not None:
        argv += ["-m", cid]
    if effort:
        argv += ["-c", f"model_reasoning_effort={json.dumps(effort)}"]
    argv += ["-s", "workspace-write", "-a", "never", "-c", "sandbox_workspace_write.network_access=true",
             "-c", 'projects={%s={trust_level="trusted"}}' % json.dumps(os.path.realpath(cwd)),
             "-c", "developer_instructions=" + json.dumps(prompt + "\n\nThe compose skill is the file " + str(skill) + ".")]
    seen = set()
    for d in [results, *_git_dirs(cwd)] + ([work, *_git_dirs(work)] if work is not None else []) + list(more):
        if d is None or (r := str(Path(d).resolve())) in seen:
            continue
        seen.add(r)
        argv += ["--add-dir", str(d)]
    return argv

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
    return HARNESSES[harness_of(model)]["argv"](model_id(model), effort, prompt, skill, cwd, results, work, more)

def once_command(model, cwd, prompt, read_only=False):
    raise NotImplementedError

def once_result(model, p):
    raise NotImplementedError

def hook_groups(key, checkout):
    raise NotImplementedError
