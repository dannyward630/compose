"""Night mode's prep: with nothing ready, a one-shot agent researches the next tickets that need planning and keeps a Linear document of questions
for the product owner's next planning session. It never shapes or plans anything and writes nothing to a ticket."""
from __future__ import annotations
import hashlib, json, os, re, subprocess, time
from pathlib import Path

import fc_claude, fc_config, fc_core, fc_delivery, fc_factorystate, fc_factoryturn, fc_nightstate, fc_plan, fc_readiness

PREP_TITLE = "Night prep: questions for the next planning session"
REFRESH_ON = ("dispatched", "verified", "held", "changed", "answered")
REFRESH_SECONDS = 1800
INTRO = "Kept current overnight by night prep. These are researched questions with a recommendation marked as a guess; nothing here is a plan or a decision."
GONE = ("done", "canceled", "cancelled", "in progress", "in review")
MAX_QUESTIONS = 5
WORKER_SECONDS = 1800 + 300  # a worker's timeout plus a margin: a pid older than this is another process's
RETRY_SECONDS = 1800
DONE = ('prepared', 'dropped')
ERRORS = (RuntimeError, ValueError, TypeError, KeyError, OSError, SystemExit, subprocess.SubprocessError)
ASK = ("You prepare the next planning session for this ticket; you never plan: do not write stories, mark anything ready, or answer your own questions. "
       "Read the code it touches, say what is built and what is still open, and write at most 5 questions the product owner must answer, "
       "each with your recommendation marked as a guess. When an old section is given, rewrite, merge, or drop its questions against what is true now; "
       "set drop when none still applies. Reply with only JSON: "
       '{"code": [str], "built": [str], "open": [str], "questions": [{"question": str, "recommendation": str, "why": str}], "drop": bool}.')

def prep_print(ticket_text: str, feature_text: str) -> str:
    return hashlib.sha256(f"{ticket_text}\0{feature_text}".encode()).hexdigest()[:16]

def _q(text, n=None) -> str:
    return " ".join(str(text).replace('"', "'").split())[:n]

def _line(text) -> str:
    """Model text as one line that cannot open a heading."""
    return " ".join(str(text).split()).lstrip("# ")

def outcomes_path(repo) -> Path:
    return fc_core.repo_link(repo).with_name("night-prep.jsonl")

def _outcome(repo, ident, status) -> None:
    path = outcomes_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as out:
        out.write(json.dumps({"ticket": ident, "status": status, "at": time.time()}) + "\n")

def _done_since(repo, ident, at) -> bool:
    try:
        lines = outcomes_path(repo).read_text().splitlines()
    except OSError:
        return False
    for line in lines:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if isinstance(r, dict) and r.get("ticket") == ident and r.get("status") in DONE and (r.get("at") or 0) >= at:
            return True
    return False

def _issue(repo, ident) -> dict:
    got = json.loads(fc_factoryturn.compose_cli(["linear", "get", ident, "--json", "--repo", str(repo)]))
    if not isinstance(got, dict):
        raise ValueError(f"no issue {ident}")
    return got

def _texts(repo, issue) -> tuple:
    """(the ticket's title and description, its feature's description): what a change to either would reopen."""
    parent = (issue.get("parent") or {}).get("identifier")
    feature = _issue(repo, parent).get("description") or "" if parent else ""
    return f"{issue.get('title') or ''}\n{issue.get('description') or ''}", feature

def candidates(repo, offer_id, limit) -> list:
    """The next tickets that need planning, from the offer on in delivery order: a feature without stories, or a story not specced."""
    plan = fc_delivery.product_plan(repo)
    if not plan or limit <= 0:
        return []
    entries = fc_plan.order_entries(plan["tracks"], plan["features"])
    start = next((i for i, e in enumerate(entries) if e["id"] == offer_id), 0)
    out = []
    for e in entries[start:]:
        if len(out) >= limit:
            break
        if e["state"].lower() not in fc_factoryturn.OPEN:
            continue
        if e["kind"] == "feature":
            out.append({"id": e["id"], "title": e["title"], "layer": "stories", "feature": e["feature"]})
            continue
        try:
            got = fc_readiness.story_readiness(repo, e["id"], write=False)
        except ERRORS:
            continue
        if not got.get("error") and (got.get("specced") is False or got.get("needs_shaping")):
            out.append({"id": e["id"], "title": e["title"], "layer": "story", "feature": e["feature"]})
    return out

def render(ticket, found: dict, model, at) -> str:
    def items(head, key):
        return [head] + [f"- {x}" for x in found.get(key) or []] + [""]
    lines = [f"## {ticket['id']}: {ticket['title']}", "",
             f"Layer: {ticket['layer']}. Prepared {at} by night prep ({model}): a likely opening, not a script.", "",
             *items("Code involved:", "code"), *items("What is built:", "built"), *items("What is still open:", "open"), "Questions:"]
    for n, q in enumerate(found.get("questions") or [], 1):
        lines += [f"{n}. {q['question']}", f"   Recommendation (a guess): {q['recommendation']} - {q['why']}"]
    return "\n".join(lines) + "\n"

def _find_doc(repo) -> tuple:
    for line in fc_factoryturn.compose_cli(["linear", "doc", "list", "--repo", str(repo)]).splitlines():
        parts = line.split(" ", 2)
        if len(parts) == 3 and parts[2].strip() == PREP_TITLE:
            return parts[0], _body(fc_factoryturn.compose_cli(["linear", "doc", "get", parts[0], "--repo", str(repo)]))
    return None, ""

def _body(shown) -> str:
    """A doc get's body: after the title line, before the section hashes."""
    out = []
    for line in shown.split("\n")[1:]:
        if line.startswith("--- section hashes"):
            break
        out.append(line)
    return "\n".join(out).rstrip("\n")

def prep_doc(repo) -> dict:
    """The prep document, created when missing. Its url is known only to the call that created it (the writes return it otherwise)."""
    ident, content = _find_doc(repo)
    if ident:
        return {"id": ident, "content": content, "url": ""}
    url = fc_factoryturn.compose_cli(["linear", "doc", "create", "--title", PREP_TITLE, "--repo", str(repo)], stdin=INTRO + "\n").strip()
    ident, content = _find_doc(repo)
    if not ident:
        raise RuntimeError("the prep document was created but is not listed")
    return {"id": ident, "content": content, "url": url}

def _heading(body, ident, title) -> str:
    return next((l for l in body.split("\n") if l.startswith(f"## {ident}:")), f"## {ident}: {title}")

def _old_section(body, ident) -> str:
    lines = body.split("\n")
    heading = next((l for l in lines if l.startswith(f"## {ident}:")), None)
    span = fc_plan.section_span(lines, heading) if heading else None
    return "\n".join(lines[span[0]:span[1]]).strip() if span else ""

def write_section(repo, ident, title, text) -> str:
    """Replace this ticket's section of the prep document, or drop it (heading too) when text is None. Returns the document's url.
    The document is read back after the write; when another writer's save has undone ours, it is redone on the fresh body (two tries in all)."""
    url = ""
    for _ in range(2):
        if text is None:
            doc_id, content = _find_doc(repo)
            if not doc_id or not any(l.startswith(f"## {ident}:") for l in content.split("\n")):
                return url
            doc = {"id": doc_id, "content": content, "url": ""}
        else:
            doc = prep_doc(repo)
        body = fc_plan.replace_section(doc["content"], _heading(doc["content"], ident, title), text or "")
        shown = fc_factoryturn.compose_cli(["linear", "doc", "update", doc["id"], "--description", "--repo", str(repo)], stdin=body)
        url = shown.strip().removeprefix("updated ").strip() or doc["url"]
        now = _find_doc(repo)[1]
        if _old_section(now, ident) == (text or "").strip():
            return url
    raise RuntimeError(f"the prep document did not keep the section of {ident}")

def _running(rec, now) -> bool:
    """Whether the record's worker still runs: a pid older than the worker's timeout is another process's."""
    pid = rec.get("pid")
    return bool(pid) and now - (rec.get("at") or 0) <= WORKER_SECONDS and _alive(pid)

def _alive(pid) -> bool:
    try:
        if os.waitpid(pid, os.WNOHANG)[0] == pid:  # our own finished child is a zombie until reaped
            return False
    except OSError:
        pass
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True

def parse_reply(reply):
    """The last JSON object in the reply that has a questions list or says drop."""
    objs, dec = [], json.JSONDecoder()
    for m in re.finditer(r"\{", reply):
        try:
            v = dec.raw_decode(reply[m.start():])[0]
        except ValueError:
            continue
        if isinstance(v, dict) and (isinstance(v.get("questions"), list) or v.get("drop")):
            objs.append(v)
    return objs[-1] if objs else None

def _strings(value) -> list:
    return [_line(x) for x in value if _line(x)] if isinstance(value, list) else []

def _clean(got) -> dict:
    qs = [{"question": _line(q.get("question") or ""), "recommendation": _line(q.get("recommendation") or ""), "why": _line(q.get("why") or "")}
          for q in got.get("questions") or [] if isinstance(q, dict)]
    return {"code": _strings(got.get("code")), "built": _strings(got.get("built")), "open": _strings(got.get("open")),
            "questions": [q for q in qs if q["question"]][:MAX_QUESTIONS], "drop": bool(got.get("drop"))}

def prep_prompt(issue, feature, plan_doc, notes, old) -> str:
    return (f"{ASK}\n\nTicket {issue.get('identifier')}: {issue.get('title')}\n{(issue.get('description') or '')[:6000]}\n\n"
            f"Its feature:\n{feature[:6000]}\n\nThe product plan:\n{plan_doc[:6000]}\n\nNight notes:\n{notes[-3000:]}\n\n"
            + (f"Old section to rewrite, merge, or drop:\n{old}\n" if old else "No old section.\n"))

def run_prep(repo, ident) -> dict:
    """The worker: research one ticket and write its section of the prep document. A failure is an event, never a crash."""
    model, effort = fc_config.NIGHT_MODEL
    since = fc_nightstate.night_since(repo)
    try:
        issue = _issue(repo, ident)
        title = _line(issue.get("title") or "") or ident
        feature = _texts(repo, issue)[1]
        try:
            plan = fc_delivery.product_plan(repo)
        except (RuntimeError, SystemExit):
            plan = None
        entries = fc_plan.order_entries(plan["tracks"], plan["features"]) if plan else []
        layer = "stories" if any(e["id"] == ident and e["kind"] == "feature" for e in entries) else "story"
        _, content = _find_doc(repo)
        prompt = prep_prompt(issue, feature, ((plan or {}).get("doc") or {}).get("content") or "", fc_nightstate.notes_tail(repo), _old_section(content, ident))
        reply = fc_claude.claude_once(repo, prompt, timeout=1800, model=fc_claude.claude_id(model), tools="Read,Grep,Glob", effort=effort, keep=8000)[1]
        got = parse_reply(reply)
        if got is None:
            fc_factorystate.add_event(repo, f'event factory=prep-failed ticket={ident} why="{_q(reply.strip(), 120)}"')
            _outcome(repo, ident, "failed")
            return {"ticket": ident, "status": "failed"}
        found = _clean(got)
        if not fc_nightstate.still_on(repo, since):  # nothing is written once the night it was started under has ended
            fc_factorystate.add_event(repo, f'event factory=prep-failed ticket={ident} why="the night ended before the prep"')
            _outcome(repo, ident, "failed")
            return {"ticket": ident, "status": "failed"}
        if found["drop"] or not found["questions"]:
            url = write_section(repo, ident, title, None)
            _outcome(repo, ident, "dropped")
            fc_factorystate.add_event(repo, f"event factory=prep-dropped ticket={ident}  (no question is left for the product owner{': ' + _q(url) if url else ''})")
            return {"ticket": ident, "status": "dropped"}
        text = render({"id": ident, "title": title, "layer": layer}, found, fc_claude.claude_id(model), time.strftime("%Y-%m-%d %H:%M"))
        url = write_section(repo, ident, title, text)
        _outcome(repo, ident, "prepared")
        fc_factorystate.add_event(repo, f"event factory=prepared ticket={ident} questions={len(found['questions'])}  (ready for the next planning session: {_q(url)})")
        return {"ticket": ident, "status": "prepared", "questions": len(found["questions"])}
    except ERRORS as e:
        fc_factorystate.add_event(repo, f'event factory=prep-failed ticket={ident} why="{_q(str(e) or type(e).__name__, 120)}"')
        return {"ticket": ident, "status": "failed"}

def refresh(repo, state, lines, now, out) -> None:
    """Keep the document true: drop the sections of tickets that moved on or became ready, and queue the ones whose text changed."""
    kinds = {m for line in lines for m in re.findall(r"factory=([\w-]+)", line)}
    prep = state.setdefault("prep", {})
    if not (kinds & set(REFRESH_ON)) and now - (state.get("prep_checked") or 0) < REFRESH_SECONDS:
        return
    state["prep_checked"] = now
    for ident, rec in list(prep.items()):
        if _running(rec, now):
            continue
        try:
            issue = _issue(repo, ident)
            gone = ((issue.get("state") or {}).get("name") or "").lower() in GONE
            if not gone and rec.get("layer", "story") == "story":
                try:
                    gone = bool(fc_readiness.story_readiness(repo, ident, write=False).get("ready"))
                except ERRORS:
                    pass  # a judge error leaves the section as it is; the text check below still runs
            if gone:
                write_section(repo, ident, _line(issue.get("title") or "") or ident, None)
                del prep[ident]
            elif rec.get("print") is not None and prep_print(*_texts(repo, issue)) != rec["print"]:
                rec["print"] = None
        except ERRORS:
            continue
    try:  # a worker's late write can bring back a section refresh dropped: nothing in state names it, so it goes
        for ident in dict.fromkeys(re.findall(r"^## ([A-Z][A-Z0-9]*-\d+):", _find_doc(repo)[1], re.M)):
            if ident not in prep:
                write_section(repo, ident, ident, None)
    except ERRORS:
        pass

def _requeue_stuck(repo, prep, now) -> None:
    """A worker that died without a prepared or dropped outcome is tried once more, half an hour after it began."""
    for ident, rec in prep.items():
        if (rec.get("pid") and not _running(rec, now) and rec.get("print") is not None and not rec.get("attempts")
                and now - (rec.get("at") or 0) >= RETRY_SECONDS and not _done_since(repo, ident, rec.get("at") or 0)):
            rec["print"], rec["attempts"] = None, 1

def prep_idle(repo, state, offer, now, out) -> None:
    """A night turn with nothing to start: refresh the document, then start one prep worker on the next unprepared ticket."""
    state.setdefault("said", {})
    refresh(repo, state, [], now, out)
    prep = state.setdefault("prep", {})
    _requeue_stuck(repo, prep, now)
    night = state.get("night") or {}
    if any(_running(r, now) for r in prep.values()) or night.get("wait") or night.get("ended") or night.get("draining") not in (None, "budget"):
        return
    try:
        for c in candidates(repo, offer["id"], fc_config.FACTORY["prep_ahead"]):
            rec = prep.get(c["id"])
            if rec and rec.get("print") is not None:
                continue
            try:
                fingerprint = prep_print(*_texts(repo, _issue(repo, c["id"])))
            except ERRORS:
                continue
            pid = fc_nightstate.spawn_once(repo, ["factory", "prep", "--repo", str(repo), "--ticket", c["id"]], "night-prep.log")
            prep[c["id"]] = {"pid": pid, "print": fingerprint, "at": now, "layer": c["layer"], "attempts": (rec or {}).get("attempts", 0)}
            return
    except ERRORS as e:
        fc_factorystate.say_once(state, "prep-error", f'event factory=prep-failed why="{_q(str(e) or type(e).__name__, 120)}"  (night prep skips this turn)', out)

fc_factoryturn.IDLE["night"] = prep_idle
