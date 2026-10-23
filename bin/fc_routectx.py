"""What Jev is shown to route a task: the cheap context first, dependency analysis only on the retry, and the hash that
tells a recorded route is still current."""

import hashlib, json, re, subprocess

import fc_tasks


def route_context(repo, proj, meta, tasks, issues):
    """The Jev state for one task: task, criteria, files, other_files, story, bug, test, signals, check, pin."""
    mine = issues.get(meta.get("linear")) or {}
    parent = issues.get(mine.get("parentId"))
    rep = re.search(r"## Reproduction\n(.*?)(?:\n## |\Z)", meta["body"], re.S)
    text = (rep.group(1) if rep else "").strip()
    case = re.search(r"^case:\s*(\S+)", text, re.M) if text else None
    name = case.group(1) if case else None
    confirmed = False
    if name and (proj / "verify.json").exists() and (proj / "results" / "prove.json").exists():
        e2e = json.loads((proj / "verify.json").read_text()).get("e2e") or []
        rows = json.loads((proj / "results" / "prove.json").read_text()).get("cases") or []
        confirmed = any(c.get("name") == name for c in e2e) and \
            any(r.get("name") == name and r.get("verdict") == "feature_missing" for r in rows)
    open_states = ("done", "canceled", "cancelled")
    other = [t for t in tasks if t["id"] != meta["id"] and (t.get("linear_state") or "").lower() not in open_states]
    files = [{"path": f, "top": f.split("/")[0] if "/" in f else ".", "exists": (repo / f).exists()} for f in meta["files"]]
    criteria = fc_tasks.parse_criteria(meta["body"])
    return {"task": meta["title"], "criteria": criteria, "files": files,
            "other_files": sorted({f for t in other for f in t["files"]}),
            "story": None if not parent else {"title": parent["title"], "criteria": fc_tasks.parse_criteria(parent["description"])},
            "bug": {"label": any(l.lower() == "bug" for l in mine.get("labels") or ()), "documented": bool(text), "confirmed": confirmed},
            "test": {"protected": meta["protected"], "command": meta["test"]} if meta.get("protected") else None,
            "signals": change_signals(repo, files, criteria),
            "pin": meta.get("route"), "check": meta["test"] if not meta.get("protected") else None}


def change_signals(repo, files, criteria):
    """What makes a change risky, counted from the task's files: docs apart from code, new files, the size of each existing one."""
    docs = [f["path"] for f in files if f["path"].endswith((".md", ".txt", ".rst"))]
    code = [f for f in files if f["path"] not in docs]
    return {"code_files": len(code), "doc_files": len(docs), "new_files": [f["path"] for f in files if not f["exists"]],
            "existing_code_files": [{"path": f["path"], "lines": len((repo / f["path"]).read_text(errors="ignore").splitlines())}
                                    for f in code if f["exists"] and (repo / f["path"]).is_file()],
            "criteria": len(criteria)}


def dependency_context(repo, meta):
    """{"callers": {path: [file, ...]}} for the task's existing files, or {"unavailable": "<why>"}."""
    def trail(*args):
        try:
            run = subprocess.run(["trail", *args, "--json"], cwd=repo, capture_output=True, text=True)
        except FileNotFoundError:
            raise LookupError("trail not installed")
        if run.returncode:
            raise LookupError(f"trail exited {run.returncode}")
        try:
            return json.loads(run.stdout)
        except ValueError:
            raise LookupError("trail gave unreadable output")

    callers = {}
    try:
        for path in meta["files"]:
            if not (repo / path).exists():
                continue
            try:
                spans = [(e["name"], *map(int, re.fullmatch(r"L(\d+)-L(\d+)", e["span"]).groups()))
                         for e in trail("skeleton", path)["entries"]]
                found = set()
                for name, lo, hi in spans:
                    if any((n, a, b) != (name, lo, hi) and a <= lo and hi <= b for n, a, b in spans):
                        continue
                    for m in trail("callers", name)["matches"]:
                        if m["symbol"]["path"] == path:
                            found.update(h["path"] for h in m["hits"])
            except (KeyError, TypeError, AttributeError):
                raise LookupError("trail gave unreadable output")
            callers[path] = sorted(found - set(meta["files"]))[:20]
    except LookupError as why:
        return {"unavailable": str(why)}
    return {"callers": callers}


def context_hash(repo, meta, policies):
    """16 hex chars of sha256 over the task body (Route left out), its files, their blobs at HEAD and the policies."""
    blobs = []
    for path in meta["files"]:
        run = subprocess.run(["git", "-C", str(repo), "rev-parse", f"HEAD:{path}"], capture_output=True, text=True)
        blobs.append(run.stdout.strip() if run.returncode == 0 else "-")
    text = json.dumps([meta["body"], meta["files"], blobs, policies], sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
