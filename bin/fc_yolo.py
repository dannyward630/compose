import json, os, sys, time
from pathlib import Path
import fc_cost, fc_core, fc_tasks, fc_worktree, fc_watch


# ---------- `yolo`: the product owner is away; the engineering manager answers with the recommendation and logs it ----------
YOLO_NEVER = ("destructive, irreversible, and security-sensitive actions are never pre-authorizable whatever the words say: "
              "anything that costs money beyond the configured models (a model or provider switch, keys), the payment halt, "
              "merging a toolsmith fix into compose itself, force-push, `clean --delete-unmerged`, `crew stop --force`, "
              "attended prompts (Frame0 Allow, sign-ins), and anything the product owner's CLAUDE.md forbids. These still stop and wait.")
def yolo_digest(repo, proj, y):
    """What the product owner reads on return, rendered only from disk: their words, the decisions, what waits, what failed, what is done, cost."""
    since = fc_core.report_time(y["since"])
    snap = fc_watch.watch_snapshot(repo, proj)
    changed = lambda tid: (f := proj / "results" / f"{tid}.json").exists() and f.stat().st_mtime >= since
    tasks = {tid: t for tid, t in snap["tasks"].items() if changed(tid)}
    waiting = [f"{n}: {r[-1]['state']}  {r[-1]['message']}" for n, r in snap["crew"].items()
               if r and r[-1]["state"] in ("needs-user", "blocked") and fc_core.report_time(r[-1]["at"]) >= since]
    if snap["halt"]:
        waiting.append(f"payment halt at {snap['halt'][1]} ({snap['halt'][2]} task(s) left): top up, then `compose resume`")
    verify = snap["verify"] if snap["verify"] and snap["verify"][0] >= since else None
    if verify and not verify[1]:
        waiting.append("verify FAIL: read results/verify.json")
    failed = [f"{tid} {t['title']}  {t['state']}" for tid, t in tasks.items() if t["state"] == "failed" or t["state"].startswith(("rejected_", "exhausted"))]
    done = [f"{tid} {t['title']}  {t['state']}" for tid, t in tasks.items() if t["state"] in ("passed", "already_green", "merged")]
    if verify and verify[1]:
        done.append("verify PASS")
    layers = proj / "layers.json"
    if layers.exists() and layers.stat().st_mtime >= since:
        done.append("stack submitted: " + ", ".join(json.loads(layers.read_text())))
    elif stack := fc_worktree.stack_order(repo, proj):
        done.append(f"stack ok locally, not pushed: {' <- '.join(stack)}")
    t = fc_cost.total(fc_cost.rows(proj))
    task_cost = sum(v["cost"] for v in snap["tasks"].values())
    sections = [("Your instructions", [y.get("words") or "(no words)", f"push: {'yes' if y.get('push') else 'no'}"]),
                ("Decided for you", [f"{d['ts']}  {d['text']}" for d in y.get("decisions", [])]),
                ("Waiting on you", waiting), ("Tried and failed", failed), ("Done", done),
                ("Cost", [f"{t['input']}in  {t['cache_created']}cc  {t['cache_read']}cr  {t['output']}out  ({t['teammates']} teammates)  tasks ${task_cost:.4f}"])]
    out = [f"yolo off for {proj.name}: away since {y['since']}"]
    for head, items in sections:
        out += ["", head] + [f"- {i}" for i in items or ["none"]]
    return "\n".join(out)

def cmd_yolo(a):
    """Enter yolo (words pre-answer questions verbatim; --push permits the stack's submit), log a decision taken, clear the words, or come back (`off`)."""
    proj = fc_core.project_dir(a); repo = Path(a.repo).resolve()
    path = proj / "results" / "yolo.json"
    y = fc_tasks.yolo_state(proj)
    words = list(a.words or [])
    if (words[:1] in (["off"], ["decided"]) or a.clear_words) and not y:
        print(f"yolo is not on for {proj.name}; `compose yolo --project {proj.name} [--push] [words]` turns it on")
        sys.exit(1)
    if a.clear_words:
        if words or a.push:
            sys.exit(f"--clear-words changes only the words; run it alone: `compose yolo --project {proj.name} --clear-words`")
        y["words"] = ""
        fc_core.atomic_write(path, json.dumps(y, indent=2))
        print(f"words cleared for {proj.name}; kept: since {y['since']}, push: {'yes' if y.get('push') else 'no'}, {len(y['decisions'])} decision(s)")
        return
    if words == ["off"]:
        print(yolo_digest(repo, proj, y))
        os.replace(path, path.with_name(f"yolo-{y['since'].replace(' ', 'T').replace(':', '')}.json"))
        return
    if words[:1] == ["decided"]:
        if len(words) < 2:
            sys.exit('yolo decided needs "<question>: <answer taken>"')
        y["decisions"].append({"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "text": " ".join(words[1:])})
        fc_core.atomic_write(path, json.dumps(y, indent=2))
        print(f"logged for the product owner's return: {' '.join(words[1:])}")
        return
    # A shell variable holding a whole command reaches here as one word (zsh never splits an unquoted one): refuse it, never store it.
    if any(w.startswith(("--repo", "--project")) for w in words) or " decided " in f" {' '.join(words)} ":
        sys.exit(f"these words look like a compose command passed as one word, so nothing changed: {' '.join(words)!r}\n"
                 f"write the command out and quote only the words:\n"
                 f"  compose yolo --project {proj.name} [--push] \"<words>\"\n"
                 f"  compose yolo decided --project {proj.name} \"<question>: <answer taken>\"\n"
                 f"words that themselves say ` decided ` are taken for a mislaid `yolo decided`: reword them")
    y = y or {"since": time.strftime("%Y-%m-%d %H:%M:%S"), "decisions": []}
    y.update(push=bool(a.push), words=" ".join(words) if words else y.get("words", ""),
             by={"role": os.environ.get("COMPOSE_ROLE") or "manager", "session": fc_core.session_id()})  # watch and status say who: fc_tasks.yolo_by
    path.parent.mkdir(parents=True, exist_ok=True)
    fc_core.atomic_write(path, json.dumps(y, indent=2))
    print(f"yolo on for {proj.name} since {y['since']}: the engineering manager answers with the recommendation and logs each answer")
    print(f"your words: {y['words'] or '(none)'}")
    print(f"push: {'yes, the verified stack is submitted' if y['push'] else 'no, the stack waits for you'}")
    print(YOLO_NEVER)
    print(f"back: `compose yolo off --project {proj.name}` prints what happened")
