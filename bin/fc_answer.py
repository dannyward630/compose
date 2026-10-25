"""Night mode's one-time frontier answerer: it settles a team lead's question on an approved ticket while the product owner sleeps."""
from __future__ import annotations
import json, os, re, time
from pathlib import Path

import fc_claude, fc_config, fc_core, fc_crew, fc_delivery, fc_factorystate, fc_factoryturn, fc_herdr, fc_models, fc_nightstate, fc_tasks, fc_yolo

ANSWERERS = 2
MORNING = ("shape ", "deep-dive ", "stories ")
ISSUE_RE = re.compile(r"\b([A-Z][A-Z0-9]*-\d+)\b")
ASK = ("Answer this question the team lead raised while building an approved ticket, as the product owner would from what is written here; "
       "read the code you need. If answering needs anything in the never-set above, or needs the product owner to plan something new, "
       'set never_set and answer nothing. Reply with only JSON: {"never_set": bool, "why_wait": str, "answer": str, "reasoning": str, '
       '"cards": {"<card id>": "<option>"}}.')

def answers_path(repo) -> Path:
    return fc_core.repo_link(repo).with_name("night-answers.jsonl")

def _records(repo) -> list:
    try:
        lines = answers_path(repo).read_text().splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out

def _feature(proj) -> str:
    try:
        return str(json.loads((proj / "linear.json").read_text()).get("feature") or "")
    except (OSError, ValueError, AttributeError):
        return ""

def new_questions(repo, night) -> list[dict]:
    """The orchestrators' needs-user reports since the night began that nobody has been asked or told about yet."""
    out = []
    for slug, (_wt, proj) in fc_core.all_projects(repo).items():
        if (fc_tasks.yolo_state(proj) or {}).get("mode") != "night":
            continue
        for r in fc_crew.crew_reports(proj, fc_herdr.agent_name(slug, "orchestrator")):
            key = f"{slug}@{r.get('at')}"
            if r.get("state") != "needs-user" or key in night["asked"] or key in night["morning"]:
                continue
            try:
                if fc_core.report_time(r["at"]) < night["since"]:
                    continue
            except (KeyError, ValueError, TypeError):
                continue
            msg = str(r.get("message") or "")
            m = ISSUE_RE.search(msg)
            out.append({"key": key, "project": slug, "at": r["at"], "message": msg, "issue": m.group(1) if m else _feature(proj)})
    return out

def kind(message) -> str:
    return "morning" if str(message).strip().lower().startswith(MORNING) else "answer"

def answer_prompt(q, chain: list[tuple[str, str]], plan_doc: str, notes: str) -> str:
    tickets = "\n\n".join(f"{ident}:\n{text}" for ident, text in chain) or "(none)"
    return (f"Question from the team lead on {q['issue']}:\n{q['message']}\n\nThe ticket and its parents:\n{tickets}\n\n"
            f"The product delivery plan:\n{plan_doc or '(none)'}\n\nThe night's notes:\n{notes or '(none)'}\n\n"
            f"Never pre-authorizable: {fc_yolo.YOLO_NEVER}\n\n{ASK}")

def comment_body(q, rec, model, date) -> str:
    return (f"Answered while you were away, by the night answerer ({model}, {date}).\n\nQuestion: {q['message']}\nAnswer: {rec['answer']}\n"
            f"Why: {rec['reasoning']}\n\nTo confirm: this is the answerer's call, not yours; overruling it in the morning is an ordinary plan change.")

def _failed(slug, message) -> str:
    return (f'event factory=answer-failed project={slug} question="{message}"  '
            "(the answerer ended without an answer: it waits for the product owner)")

def _chain(repo, issue) -> list[tuple[str, str]]:
    chain, seen = [], set()
    while issue and issue not in seen and len(chain) < 4:
        seen.add(issue)
        try:
            data = json.loads(fc_factoryturn.compose_cli(["linear", "get", issue, "--json", "--repo", str(repo)]))
        except (RuntimeError, ValueError):
            break
        if not isinstance(data, dict):
            break
        chain.append((issue, f"{data.get('title') or ''}\n{data.get('description') or ''}".strip()))
        issue = (data.get("parent") or {}).get("identifier") if isinstance(data.get("parent"), dict) else None
    return chain

def run_answer(repo, slug, at) -> dict:
    """The worker: answer one question, record it on the issue and in the lead, and return the record."""
    wt, proj = fc_core.all_projects(repo)[slug]
    q = next(x for x in new_questions_for(repo, slug, proj, at))
    try:
        plan = fc_delivery.product_plan(repo)
        doc = ((plan or {}).get("doc") or {}).get("content") or ""
    except (RuntimeError, SystemExit):
        doc = ""
    model, effort = fc_config.NIGHT_MODEL
    rec = {"key": q["key"], "project": slug, "issue": q["issue"], "question": q["message"], "answer": "", "reasoning": "", "cards": {},
           "never_set": False, "why_wait": "", "model": model, "at": time.strftime("%Y-%m-%d %H:%M:%S"), "error": ""}
    try:
        prompt = answer_prompt(q, _chain(repo, q["issue"]), doc, fc_nightstate.notes_tail(repo))
        reply = fc_claude.claude_once(wt, prompt, timeout=1800, model=fc_claude.claude_id(model), tools="Read,Grep,Glob", effort=effort, keep=6000)[1]
        got = fc_models.lenient_json(reply, key="answer")
        if not isinstance(got, dict) or "answer" not in got:
            raise ValueError("no answer in the reply")
    except (RuntimeError, ValueError, TypeError) as e:
        rec["error"] = str(e)[:300] or "unparsable reply"
        _append(repo, rec)
        fc_factorystate.add_event(repo, _failed(slug, q["message"]))
        return rec
    cards = got.get("cards") if isinstance(got.get("cards"), dict) else {}
    rec.update(never_set=bool(got.get("never_set")), why_wait=str(got.get("why_wait") or ""), answer=str(got.get("answer") or ""),
               reasoning=str(got.get("reasoning") or ""), cards={str(k): str(v) for k, v in cards.items()})
    if rec["never_set"] or not rec["answer"].strip():
        rec["never_set"] = True
        _append(repo, rec)
        fc_nightstate.add_note(repo, f"{slug} {q['issue']}: never-set, waits for the product owner ({rec['why_wait']})")
        fc_factorystate.add_event(repo, f'event factory=waiting project={slug} question="{q["message"]}" why="{rec["why_wait"]}"  '
                                        "(never-set: it waits for the product owner; send one PushNotification naming it and the recommendation)")
        return rec
    fc_factoryturn.compose_cli(["linear", "comment", q["issue"], "--repo", str(repo)], stdin=comment_body(q, rec, model, time.strftime("%Y-%m-%d")))
    if rec["cards"]:
        for card, option in rec["cards"].items():
            fc_factoryturn.compose_cli(["decide", "--repo", str(repo), "--project", slug, f"{card}: {option}"])
    else:
        fc_factoryturn.prompt_lead(fc_herdr.agent_name(slug, "orchestrator"), f"night: {rec['answer']}")
    _append(repo, rec)
    fc_nightstate.add_note(repo, f"{slug} {q['issue']}: answered {rec['answer'][:200]}")
    fc_factorystate.add_event(repo, f'event factory=answered project={slug} issue={q["issue"]} answer="{rec["answer"][:120]}"  '
                                    "(the night answerer settled it; it is listed under To confirm in the morning)")
    return rec

def _append(repo, rec) -> None:
    path = answers_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as out:
        out.write(json.dumps(rec) + "\n")

def new_questions_for(repo, slug, proj, at) -> list[dict]:
    """The report `at` of project `slug`, as new_questions shapes it, whether or not it was asked already."""
    for r in fc_crew.crew_reports(proj, fc_herdr.agent_name(slug, "orchestrator")):
        if r.get("at") == at:
            msg = str(r.get("message") or "")
            m = ISSUE_RE.search(msg)
            return [{"key": f"{slug}@{at}", "project": slug, "at": at, "message": msg, "issue": m.group(1) if m else _feature(proj)}]
    raise RuntimeError(f"no report of {slug} at {at}")

def _alive(pid) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True

def answer_step(repo, state, now) -> list[str]:
    night, lines = state["night"], []
    done = {r.get("key") for r in _records(repo)}
    for key, a in night["asked"].items():
        if not a.get("done") and not _alive(a["pid"]):
            a["done"] = True
            if key not in done:
                lines.append(_failed(a["project"], a["message"]))
    running = sum(1 for a in night["asked"].values() if not a.get("done"))
    for q in new_questions(repo, night):
        if kind(q["message"]) == "morning":
            night["morning"].append(q["key"])
            lines.append(f'event factory=for-morning project={q["project"]} question="{q["message"]}"  '
                         "(planning waits for the product owner: it is listed under Ready to plan)")
        elif running < ANSWERERS:
            pid = fc_nightstate.spawn_once(repo, ["factory", "answer", "--repo", str(repo), "--project", q["project"], "--at", q["at"]], "night-answer.log")
            night["asked"][q["key"]] = {"pid": pid, "at": now, "project": q["project"], "issue": q["issue"], "message": q["message"]}
            running += 1
    return lines
