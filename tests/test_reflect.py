import importlib.machinery, importlib.util, io, json, os, subprocess, tempfile, time, unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "fast-coding")))
fc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fc)

MAP = """## Destination
Drafts survive a reload.

## Decisions so far
- Store drafts in localStorage
- ~~Autosave every keystroke~~ (C1)
- Autosave every 5 seconds (C1: keystrokes flooded the API, see ENG-9)
1. Show a toast on save

## Not yet specified
- Conflict handling
"""


def project(description=MAP):
    """A project dir whose last sync holds `description` as the feature's map, synced just now."""
    proj = Path(tempfile.mkdtemp()) / "hw"
    (proj / "results").mkdir(parents=True)
    (proj / "linear.json").write_text(json.dumps({"feature": "ENG-1"}))
    (proj / "results" / "tasks.json").write_text(json.dumps({"synced_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "feature": {"id": "ENG-1", "title": "Drafts", "description": description}, "tasks": [], "issues": {}}))
    return proj


def answers(**choices):
    """A Jev reply: answers(d0=("BROKEN", 0.8)) puts 0.8 on BROKEN for question d0."""
    return {"model": "jev-test", "answers": {k: {"choice": c, "probabilities": {c: p}} for k, (c, p) in choices.items()}}


class Reflect(unittest.TestCase):
    def setUp(self):
        for name, value in (("ENV_FILE", Path(tempfile.mkdtemp()) / "none.env"), ("say", lambda m: None)):
            p = mock.patch.object(fc, name, value); p.start(); self.addCleanup(p.stop)
        p = mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": "ts-test"}); p.start(); self.addCleanup(p.stop)

    def test_decision_lines_are_the_live_items_of_their_section(self):
        self.assertEqual(fc.decision_lines(MAP), ["Store drafts in localStorage",
                                                 "Autosave every 5 seconds (C1: keystrokes flooded the API, see ENG-9)",
                                                 "Show a toast on save"])
        self.assertEqual(fc.decision_lines("## Destination\nx\n"), [])
        self.assertEqual(fc.map_section(MAP, "Destination"), "Drafts survive a reload.")

    def test_one_question_per_line_and_flags_at_the_threshold(self):
        proj = project()
        reply = answers(d0=("BROKEN", 0.82), d1=("HOLDS", 0.9), d2=("UNCLEAR", 0.6), d3=("UNCLEAR", 0.59))
        with mock.patch.object(fc, "jev_ask", return_value=reply) as ask:
            path, rec = fc.reflect(proj, "task:003", "localStorage is wiped by the sandbox",
                                   against=["Task 003 brief: use localStorage.setItem"])
        state, questions = ask.call_args.args[2], ask.call_args.args[3]
        self.assertEqual(len(questions), 4)  # three live decisions plus the quoted line
        self.assertEqual(questions["d3"]["instructions"]["line"], "Task 003 brief: use localStorage.setItem")
        self.assertEqual(state["destination"], "Drafts survive a reload.")
        self.assertIn("localStorage is wiped", state["evidence"])
        self.assertEqual([v["line"] for v in rec["flagged"]], ["Store drafts in localStorage", "Show a toast on save"])
        self.assertEqual(json.loads(path.read_text())["trigger"], "task:003")

    def test_no_decisions_and_nothing_against_asks_nothing(self):
        proj = project("## Destination\nx\n")
        with mock.patch.object(fc, "jev_ask") as ask:
            path, rec = fc.reflect(proj, "verify", "a finding")
        ask.assert_not_called()
        self.assertEqual((rec["verdicts"], rec["flagged"], rec.get("error")), ([], [], None))
        self.assertTrue(path.exists())

    def test_a_screen_that_cannot_run_records_why_and_never_raises(self):
        proj = project()
        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": ""}):
            _, rec = fc.reflect(proj, "verify", "x")
        self.assertIn("TYPESAFE_API_KEY", rec["error"])
        with mock.patch.object(fc, "jev_ask", side_effect=fc.PaymentRequired("typesafe", "out of credits")):
            _, rec = fc.reflect(proj, "verify", "x")
        self.assertIn("out of credits", rec["error"])

    def test_evidence_builds_up_until_a_change_closes(self):
        proj = project()
        rows = [{"at": "2026-10-11 10:00:00", "trigger": "task:001", "text": "first failure"},
                {"at": "2026-10-11 10:05:00", "trigger": "task:002", "text": "second failure"}]
        (proj / "results" / "evidence.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
        with mock.patch.object(fc, "jev_ask", return_value=answers()) as ask:
            fc.reflect(proj, "task:003", "third failure")
        ev = ask.call_args.args[2]["evidence"]
        self.assertLess(ev.index("third"), ev.index("second"))  # newest first
        self.assertIn("first failure", ev)
        fc.changes_dir(proj).mkdir(parents=True)
        (fc.changes_dir(proj) / "C1.json").write_text(json.dumps({"id": "C1", "done_at": "2026-10-11 10:03:00"}))
        with mock.patch.object(fc, "jev_ask", return_value=answers()) as ask:
            fc.reflect(proj, "task:004", "fourth failure")
        ev = ask.call_args.args[2]["evidence"]
        self.assertNotIn("first failure", ev)  # a closed change already acted on it
        self.assertIn("second failure", ev)

    def test_reflects_in_the_same_second_get_their_own_files(self):
        proj = project()
        with mock.patch.object(fc, "jev_ask", return_value=answers()):
            paths = {fc.reflect(proj, f"task:00{i}", "x")[0] for i in range(3)}
        self.assertEqual(len(paths), 3)

    def test_the_command_prints_each_verdict(self):
        proj = project()
        out = io.StringIO()
        with mock.patch.object(fc, "project_dir", lambda a: proj), \
                mock.patch.object(fc, "jev_ask", return_value=answers(d0=("BROKEN", 0.9))), \
                mock.patch("sys.stdin", io.StringIO("captain: drafts must sync across devices\n")), redirect_stdout(out):
            fc.cmd_reflect(SimpleNamespace(evidence="-", against=None))
        self.assertIn("BROKEN", out.getvalue())
        self.assertIn("Store drafts in localStorage", out.getvalue())
        self.assertIn("flagged 1 of 3", out.getvalue())


class WatchReflect(unittest.TestCase):
    def snap(self, reflects):
        return {"tasks": {}, "agents": {}, "run": False, "verify": None, "crew": {}, "reflects": reflects}

    def test_flagged_screens_and_errors_wake_the_orchestrator_once(self):
        after = self.snap({"/p/r1.json": {"trigger": "task:003", "error": None, "counts": (1, 0)},
                           "/p/r2.json": {"trigger": "verify", "error": None, "counts": (0, 0)},
                           "/p/r3.json": {"trigger": "task:004", "error": "no TYPESAFE_API_KEY", "counts": (0, 0)}})
        ev = fc.watch_events(self.snap({}), after)
        self.assertEqual(len(ev), 2)
        self.assertEqual(ev[0], "event reflect=/p/r1.json broken=1 unclear=0 trigger=task:003")
        self.assertTrue(ev[1].startswith("event reflect=/p/r3.json error='no TYPESAFE_API_KEY'"))
        self.assertEqual(fc.watch_events(after, after), [])

    def test_the_first_mate_does_not_get_screens(self):
        ev = ["event reflect=/p/r1.json broken=1 unclear=0 trigger=task:003"]
        self.assertEqual(fc.watch_filter(ev, "hw", ["hw-orchestrator"]), [])
        self.assertEqual(fc.watch_filter(ev, "hw", []), ev)

    def test_the_snapshot_drops_screens_a_closed_change_answered(self):
        proj = project()
        with mock.patch.object(fc, "jev_ask", return_value=answers(d0=("BROKEN", 0.9))), mock.patch.object(fc, "say", lambda m: None), \
                mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": "ts-test"}):
            path, _ = fc.reflect(proj, "task:001", "x")
        with mock.patch.object(fc, "herdr", return_value={}):
            self.assertEqual(fc.watch_snapshot(Path("."), proj)["reflects"][str(path)]["counts"], (1, 0))
            fc.changes_dir(proj).mkdir(parents=True)
            (fc.changes_dir(proj) / "C1.json").write_text(json.dumps({"id": "C1", "done_at": "2999-01-01 00:00:00"}))
            self.assertEqual(fc.watch_snapshot(Path("."), proj)["reflects"], {})

    def test_a_screen_written_between_two_watches_is_reported_by_the_next(self):
        proj = project()
        def watch(now):
            out, a = [], SimpleNamespace(repo=".", now=now, from_=None, timeout=0.05, interval=0.01, stall=10_000)
            with mock.patch.object(fc, "project_dir", return_value=proj), mock.patch.object(fc, "herdr", return_value={}), \
                    mock.patch("builtins.print", out.append):
                try:
                    fc.cmd_watch(a)
                except SystemExit:
                    pass
            return out
        watch(now=True)
        with mock.patch.object(fc, "jev_ask", return_value=answers(d0=("BROKEN", 0.9))), mock.patch.object(fc, "say", lambda m: None), \
                mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": "ts-test"}):
            path, _ = fc.reflect(proj, "task:001", "x")  # while no watch runs
        out = watch(now=False)
        self.assertTrue(any(f"event reflect={path} broken=1" in line for line in out), out)
        self.assertIn("event timeout", watch(now=False)[-1])  # reported once

    def test_an_unreadable_change_file_does_not_hide_the_closed_ones(self):
        proj = project()
        fc.changes_dir(proj).mkdir(parents=True)
        (fc.changes_dir(proj) / "C1.json").write_text("{not json")
        (fc.changes_dir(proj) / "C2.json").write_text(json.dumps({"id": "C2", "done_at": "2026-10-11 10:03:00"}))
        self.assertEqual(fc.last_change_done(proj), "2026-10-11 10:03:00")


def task(tid, after=""):
    return {"id": tid, "title": f"task {tid}", "files": [f"{tid}.txt"], "protected": [], "test": "true", "model": "pi:x/y",
            "after": after, "linear": f"ENG-{int(tid)}", "linear_state": "Todo", "body": "## Goal\nx"}


def with_tasks(proj, tasks):
    cache = json.loads((proj / "results" / "tasks.json").read_text())
    cache["tasks"] = tasks
    (proj / "results" / "tasks.json").write_text(json.dumps(cache))


def run_all(proj, status=None, during=None, reflect=None):
    """run_tasks over every synced task with run_task faked: each passes unless `status` says otherwise, and `during(id)` runs
    inside it. Returns (ids run in order, the printed table, the reflect mock)."""
    calls, reflect = [], reflect or mock.MagicMock(return_value=(Path("/p/reflect.json"), {}))
    def fake(repo, proj_, meta, attempts):
        calls.append(meta["id"])
        if during:
            during(meta["id"])
        st = (status or {}).get(meta["id"], "passed")
        log = [{"contradiction": "the brief says x / the code shows y, a.txt:1"}] if st == "contradiction" else \
              [{"test_output": "AssertionError: expected 2, got 3"}]
        return {"id": meta["id"], "title": meta["title"], "status": st, "attempts": 1, "seconds": 0.0, "cost": 0.0, "branch": "-", "log": log}
    out = io.StringIO()
    with mock.patch.object(fc, "run_task", fake), mock.patch.object(fc, "preflight", lambda m: None), \
            mock.patch.object(fc, "stack_order", lambda r, p: []), mock.patch.object(fc, "herdr_space", lambda p: None), \
            mock.patch.object(fc, "triage", lambda *x: None), mock.patch.object(fc, "reflect", reflect), redirect_stdout(out):
        try:
            fc.run_tasks(Path("."), proj, fc.load_tasks(proj), SimpleNamespace(trunk="main", parallel=1, attempts=1, no_stack=True))
        except SystemExit:
            pass
    return calls, out.getvalue(), reflect


class Holds(unittest.TestCase):
    def setUp(self):
        self.proj = project()
        with_tasks(self.proj, [task("001"), task("002", "001"), task("003", "002"), task("004")])
        self.said, self.notes = [], []
        fc._hold_warned.clear()
        for name, value in (("say", self.said.append), ("project_dir", lambda a: self.proj),
                            ("linear_note", lambda meta, body: self.notes.append((meta["id"], body)))):
            p = mock.patch.object(fc, name, value); p.start(); self.addCleanup(p.stop)

    def hold(self, **kw):
        out = io.StringIO()
        with redirect_stdout(out):
            fc.cmd_hold(SimpleNamespace(**{"only": None, "reason": None, "release": None, **kw}))
        return out.getvalue()

    def test_hold_and_release_write_the_file_and_comment_on_linear(self):
        self.hold(only="002,003", reason="D2 broken")
        self.assertEqual(set(fc.held(self.proj)), {"002", "003"})
        self.assertEqual(self.notes, [("002", "Held: D2 broken"), ("003", "Held: D2 broken")])
        self.hold(release="002")
        self.assertEqual(set(fc.held(self.proj)), {"003"})
        self.hold(release="all")
        self.assertEqual(fc.held(self.proj), {})
        self.assertEqual(self.notes[-2:], [("002", "Released"), ("003", "Released")])

    def test_hold_needs_ids_and_a_reason(self):
        with self.assertRaises(SystemExit):
            self.hold(only="002")

    def test_a_run_skips_held_tasks_and_leaves_them_pending(self):
        self.hold(only="002", reason="D2 broken")
        calls, table, _ = run_all(self.proj)
        self.assertEqual(calls, ["001", "004"])
        self.assertIn("002 held    D2 broken", self.said)
        self.assertIn("003 held    after held 002", self.said)
        self.assertNotIn("blocked_by", table)

    def test_a_failure_still_blocks_what_waits_on_it(self):
        self.hold(only="004", reason="x")
        _, table, _ = run_all(self.proj, status={"001": "failed"})
        self.assertIn("blocked_by_001", table)
        self.assertIn("004 held    x", self.said)

    def test_a_release_during_the_run_lets_the_task_start(self):
        self.hold(only="004", reason="x")
        calls, _, _ = run_all(self.proj, during=lambda tid: tid == "001" and self.hold(release="004"))
        self.assertIn("004", calls)

    def test_an_unreadable_hold_file_holds_nothing(self):
        (self.proj / "results" / "hold.json").write_text("{not json")
        self.assertEqual(fc.held(self.proj), {})
        self.assertEqual(len(self.said), 1)
        self.assertTrue(self.said[0].startswith("hold.json unreadable"))
        fc.held(self.proj)
        self.assertEqual(len(self.said), 1)

    def test_a_missing_hold_file_is_not_a_warning(self):
        self.assertEqual(fc.held(self.proj), {})
        self.assertEqual(self.said, [])

    def test_hold_leaves_no_temp_file_and_a_parseable_hold_json(self):
        self.hold(only="002", reason="x")
        self.assertFalse((self.proj / "results" / "hold.json.tmp").exists())
        self.assertIn("002", json.loads((self.proj / "results" / "hold.json").read_text()))

    def test_status_shows_held_with_the_reason(self):
        self.hold(only="002", reason="D2 broken")
        with mock.patch.object(fc, "sh", return_value=SimpleNamespace(returncode=1, stdout="")):
            row = fc.task_state(Path("."), self.proj, task("002", "001"), "HEAD")
        self.assertEqual((row["state"], row["note"]), ("held", "D2 broken"))


class ImplementerContradiction(unittest.TestCase):
    def run_with(self, reply):
        """One task whose test can never pass, with an implementer that always answers `reply`. Returns (result, prompts)."""
        root = Path(tempfile.mkdtemp())
        repo, proj = root / "repo", root / "proj"
        repo.mkdir(); proj.mkdir()
        git = lambda *a: subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True)
        git("init", "-q", "-b", "main")
        (repo / "a.txt").write_text("no\n")
        git("add", "-A"); git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
        meta = {"id": "001", "title": "answer", "files": ["a.txt"], "protected": [], "test": "grep -q yes a.txt",
                "model": "pi:p/primary", "after": "", "linear": "ENG-1", "body": "## Goal\nCall answer() from a.txt."}
        prompts = []
        def impl(cwd, model, prompt, session=None, task=None):
            prompts.append(prompt)
            return "s", reply, 1, {"tokens_in": 1, "tokens_out": 1, "cost": 0.0}
        with mock.patch.object(fc, "implementer", impl), mock.patch.object(fc, "graft_pack", return_value=""), \
                mock.patch.object(fc, "say", lambda m: None), \
                mock.patch.dict(os.environ, {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}):
            return fc.run_task(repo, proj, meta, 3), prompts

    def test_a_contradiction_ends_the_task_without_more_attempts(self):
        found = "the brief says a.txt exports answer() / a.txt is plain text, a.txt:1"
        r, prompts = self.run_with(f"Read a.txt.\nCONTRADICTION: {found}")
        self.assertEqual((r["status"], r["attempts"], len(prompts)), ("contradiction", 1, 1))
        self.assertEqual(r["log"][-1]["contradiction"], found)
        self.assertIn("CONTRADICTION: <what the brief says>", prompts[0])
        self.assertIn("contradiction", fc.FINAL_STATES)

    def test_echoing_the_template_is_not_a_contradiction(self):
        r, prompts = self.run_with("Rules noted.\nCONTRADICTION: <what the brief says> / <what the code shows, file:line>")
        self.assertEqual((r["status"], len(prompts)), ("failed", 3))

    def test_only_a_line_that_starts_with_it_counts(self):
        self.assertIsNone(fc.contradiction("I would write CONTRADICTION: x / y if I found one"))
        self.assertEqual(fc.contradiction("a\nCONTRADICTION: first / one\nCONTRADICTION: last / two"), "last / two")


class AutoReflect(unittest.TestCase):
    def setUp(self):
        self.proj = project()
        with_tasks(self.proj, [task("001"), task("002")])
        self.said = []
        p = mock.patch.object(fc, "say", self.said.append); p.start(); self.addCleanup(p.stop)

    def test_a_task_that_does_not_pass_is_screened(self):
        _, _, reflect = run_all(self.proj, status={"001": "failed"})
        self.assertEqual(reflect.call_count, 1)
        trigger, evidence = reflect.call_args.args[1:3]
        self.assertEqual(trigger, "task:001")
        self.assertIn("ended failed after 1 attempt(s): AssertionError: expected 2, got 3", evidence)

    def test_a_contradiction_is_screened_against_the_brief_line(self):
        _, _, reflect = run_all(self.proj, status={"002": "contradiction"})
        self.assertEqual(reflect.call_args.args[1], "task:002")
        self.assertEqual(reflect.call_args.kwargs["against"], ["the brief says x"])

    def test_a_screen_that_crashes_never_stops_the_run(self):
        calls, table, _ = run_all(self.proj, status={"001": "failed"}, reflect=mock.MagicMock(side_effect=RuntimeError("disk full")))
        self.assertEqual(calls, ["001", "002"])
        self.assertTrue(any(m.startswith("001 reflect failed (disk full)") for m in self.said), self.said)
        self.assertIn("002", table)

    def test_a_crew_contradiction_is_screened(self):
        reflect = mock.MagicMock(return_value=(Path("/p/reflect.json"), {"flagged": []}))
        msg = "the API returns a list; Linear says: returns a dict (ENG-7); evidence: api.py:40".split()
        with mock.patch.object(fc, "reflect", reflect), mock.patch.object(fc, "project_dir", lambda a: self.proj), \
                mock.patch.object(fc, "crew_attention", lambda *a: None), redirect_stdout(io.StringIO()):
            fc.cmd_report(SimpleNamespace(as_="hw-tests-003", state="contradiction", message=msg))
        self.assertEqual(reflect.call_args.args[1], "contradiction:hw-tests-003")
        self.assertEqual(reflect.call_args.kwargs["against"], ["returns a dict"])

    def test_every_crew_brief_says_how_to_report_one(self):
        with mock.patch.object(fc, "project_worktree", lambda p: Path("/wt")):
            text = fc.crew_preamble(self.proj, "hw-groundwork", "groundwork")
        self.assertIn('contradiction "<what you found>; Linear says: <quoted line> (<issue>); evidence:', text)

    def test_a_failed_verify_is_screened_with_its_findings(self):
        reflect = mock.MagicMock(return_value=(Path("/p/reflect-1.json"), {}))
        with mock.patch.object(fc, "reflect", reflect):
            fc.verify_failed(self.proj, [{}, {}], "confirmed [high] s.go: a query per answer")
            self.assertEqual(reflect.call_args.args[1], "verify")
            self.assertIn("after 2 round(s)", reflect.call_args.args[2])
            self.assertIn("a query per answer", reflect.call_args.args[2])
            reflect.reset_mock()
            fc.verify_failed(self.proj, [{}], "  ")  # only tool errors failed: nothing about the app to screen
            reflect.assert_not_called()


BLOCK = "\n\n```fast-coding\nid: {tid}\nfiles: {tid}.txt\ntest: true\n```\n"


def issue(tid, goal, status="Todo", blocked=()):
    return {"title": f"task {tid}", "description": f"## Goal\n{goal}" + BLOCK.format(tid=tid), "status": status, "blockedBy": sorted(blocked)}


BEFORE = {"ENG-3": issue("003", "Save to localStorage."), "ENG-4": issue("004", "Read from localStorage.", blocked=["ENG-3"])}
AFTER = {"ENG-3": issue("003", "Save to the server."), "ENG-4": issue("004", "Read from localStorage.", status="Canceled"),
         "ENG-5": issue("005", "Read from the server.", blocked=["ENG-3"])}
MAP_AFTER = MAP.replace("- Store drafts in localStorage\n",
                        "- ~~Store drafts in localStorage~~ (C1)\n- Store drafts on the server (C1: the sandbox wipes localStorage)\n")


def synced(proj, description, issues, ahead=0):
    """Sync the feature and `issues` (id -> issue) the way the orchestrator does, stamped `ahead` seconds from now."""
    fc.sync_tasks(proj, {"feature": {"id": "ENG-1", "title": "Drafts", "description": description},
                         "issues": [{"id": i, **v} for i, v in issues.items()]})
    cache = json.loads((proj / "results" / "tasks.json").read_text())
    cache["synced_at"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() + ahead))
    (proj / "results" / "tasks.json").write_text(json.dumps(cache))


def git_repo(branches):
    """A repo with one commit and a task branch fast/hw/<id> for each id. Returns (path, git)."""
    repo = Path(tempfile.mkdtemp())
    git = lambda *a: subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()
    git("init", "-q", "-b", "main")
    (repo / "a.txt").write_text("1\n")
    git("add", "-A"); git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
    for b in branches:
        git("branch", f"fast/hw/{b}")
    return repo, git


def change(proj, repo, action, cid=None, why=None):
    out = io.StringIO()
    with mock.patch.object(fc, "project_dir", lambda a: proj), redirect_stdout(out):
        fc.cmd_change(SimpleNamespace(repo=str(repo), action=action, id=cid, why=why))
    return out.getvalue()


class Changes(unittest.TestCase):
    def setUp(self):
        self.proj = project()
        self.repo, self.git = git_repo(("003", "004"))
        for name, value in (("say", lambda m: None), ("LINEAR_KEY", None)):
            p = mock.patch.object(fc, name, value); p.start(); self.addCleanup(p.stop)
        synced(self.proj, MAP, BEFORE)

    def test_sync_keeps_every_issue_whole(self):
        issues = fc.linear_cache(self.proj)["issues"]
        self.assertEqual(issues["ENG-4"], BEFORE["ENG-4"])

    def test_start_snapshots_linear_and_saves_each_branch_tip(self):
        self.assertIn("C1 open: localStorage is wiped", change(self.proj, self.repo, "start", why="localStorage is wiped"))
        rec = fc.load_change(self.proj, "C1")
        self.assertEqual(rec["before"]["issues"]["ENG-4"]["blockedBy"], ["ENG-3"])
        tip = self.git("rev-parse", "fast/hw/003")
        self.assertEqual(rec["tips"]["003"], tip)
        self.assertEqual(self.git("rev-parse", "refs/fast-coding/hw/C1/003"), tip)
        self.assertEqual(fc.open_change(self.proj), "C1")
        self.assertEqual(fc.change_line(self.proj), "  CHANGE C1 open: localStorage is wiped")

    def test_start_needs_a_fresh_sync_and_no_open_change(self):
        synced(self.proj, MAP, BEFORE, ahead=-600)
        with self.assertRaises(SystemExit):
            change(self.proj, self.repo, "start", why="x")
        synced(self.proj, MAP, BEFORE)
        change(self.proj, self.repo, "start", why="x")
        with self.assertRaises(SystemExit):
            change(self.proj, self.repo, "start", why="y")

    def test_done_records_what_changed_and_why(self):
        change(self.proj, self.repo, "start", why="localStorage is wiped by the sandbox.")
        with self.assertRaises(SystemExit):
            change(self.proj, self.repo, "done")  # no sync since the start
        synced(self.proj, MAP_AFTER, AFTER, ahead=2)
        out = change(self.proj, self.repo, "done")
        self.assertIn("C1: localStorage is wiped by the sandbox. Superseded: Store drafts in localStorage. "
                      "Canceled 004. New 005. Edited 003. Evidence: none recorded.", out)
        self.assertIn("post the comment above on ENG-1 through Linear", out)
        self.assertIsNone(fc.open_change(self.proj))
        self.assertTrue(fc.load_change(self.proj, "C1")["diff"]["feature"])

    def test_keeping_the_plan_is_recorded_too(self):
        change(self.proj, self.repo, "start", why="the captain keeps localStorage")
        synced(self.proj, MAP, BEFORE, ahead=2)
        self.assertIn("C1: the captain keeps localStorage. No changes: the plan stays as it was.", change(self.proj, self.repo, "done"))

    def test_a_canceled_issue_the_sync_no_longer_lists_still_counts(self):
        change(self.proj, self.repo, "start", why="x")
        synced(self.proj, MAP, {"ENG-3": BEFORE["ENG-3"]}, ahead=2)
        change(self.proj, self.repo, "done")
        self.assertEqual(fc.load_change(self.proj, "C1")["diff"]["canceled"], ["ENG-4"])

    def test_records_are_written_atomically(self):
        d = fc.changes_dir(self.proj)
        change(self.proj, self.repo, "start", why="x")
        self.assertEqual([f.name for f in d.iterdir()], ["C1.json"])
        synced(self.proj, MAP_AFTER, AFTER, ahead=2)
        change(self.proj, self.repo, "done")
        self.assertEqual([f.name for f in d.iterdir()], ["C1.json"])
        self.assertTrue(fc.load_change(self.proj, "C1")["done_at"])

    def test_stray_files_do_not_break_numbering(self):
        d = fc.changes_dir(self.proj)
        d.mkdir(parents=True, exist_ok=True)
        (d / "C1.json.tmp").write_text('{"id": "C1", "wh')
        (d / "Cx.json").write_text("{}")
        self.assertIn("C1 open", change(self.proj, self.repo, "start", why="x"))
        self.assertEqual(fc.change_ids(self.proj), ["C1"])

    def test_status_survives_an_unreadable_change_record(self):
        d = fc.changes_dir(self.proj)
        d.mkdir(parents=True, exist_ok=True)
        (d / "C1.json").write_text('{"id": "C1", "wh')
        self.assertTrue(fc.change_line(self.proj).startswith("  CHANGE records unreadable"))


STATE_TYPES = {"Todo": "unstarted", "In Progress": "started", "In Review": "started", "Done": "completed", "Canceled": "canceled"}


class LinearIssues:
    """Linear's GraphQL API in memory, enough for undo: issues with a description, a state, and their blockers."""
    def __init__(self, issues, feature_description):
        self.issues = {i: {"description": v["description"], "status": v["status"], "blockedBy": list(v["blockedBy"])} for i, v in issues.items()}
        self.issues["ENG-1"] = {"description": feature_description, "status": "In Progress", "blockedBy": []}
        self.fail_on, self.comments = None, []

    def __call__(self, query, v):
        if "inverseRelations" in query:
            i = v["id"]
            return {"issue": {"inverseRelations": {"nodes": [{"id": f"{b}|{i}", "type": "blocks", "issue": {"id": b, "identifier": b}}
                                                             for b in self.issues[i]["blockedBy"]]}}}
        if "issueRelationDelete" in query:
            b, i = v["id"].split("|")
            self.issues[i]["blockedBy"].remove(b)
            return {"issueRelationDelete": {"success": True}}
        if "issueRelationCreate" in query:
            self.issues[v["b"]]["blockedBy"].append(v["a"])
            return {"issueRelationCreate": {"success": True}}
        if "issueUpdate" in query:
            if v["id"] == self.fail_on:
                raise RuntimeError("Linear is down")
            if "in" in v:
                self.issues[v["id"]].update(v["in"])
            else:
                self.issues[v["id"]]["status"] = v["s"][2:]
            return {"issueUpdate": {"success": True}}
        if "commentCreate" in query:
            self.comments.append((v["id"], v["b"]))
            return {"commentCreate": {"success": True}}
        i = v["id"]
        return {"issue": {"id": i, "identifier": i, "state": {"name": self.issues[i]["status"], "type": STATE_TYPES[self.issues[i]["status"]]},
                          "team": {"states": {"nodes": [{"id": f"s-{n}", "name": n, "type": t} for n, t in STATE_TYPES.items()]}},
                          "parent": None, "children": {"nodes": []}}}


class Undo(unittest.TestCase):
    def setUp(self):
        self.proj = project()
        self.repo, self.git = git_repo(("003", "004"))
        self.lin = LinearIssues(AFTER, MAP_AFTER)
        for name, value in (("say", lambda m: None), ("LINEAR_KEY", "lin_test"), ("linear_gql", self.lin),
                            ("register_stack", lambda *a, **k: None)):
            p = mock.patch.object(fc, name, value); p.start(); self.addCleanup(p.stop)
        synced(self.proj, MAP, BEFORE)
        change(self.proj, self.repo, "start", why="localStorage is wiped by the sandbox")
        rebuilt = self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit-tree", "HEAD^{tree}", "-p", "HEAD", "-m", "rebuilt")
        self.git("branch", "-f", "fast/hw/003", rebuilt)  # the re-plan redid layer 003
        synced(self.proj, MAP_AFTER, AFTER, ahead=2)
        change(self.proj, self.repo, "done")
        synced(self.proj, MAP_AFTER, AFTER, ahead=3)

    def test_undo_puts_back_every_issue_and_layer(self):
        old = self.git("rev-parse", "refs/fast-coding/hw/C1/003")
        out = change(self.proj, self.repo, "undo", cid="C1")
        self.assertEqual(self.lin.issues["ENG-3"]["description"], BEFORE["ENG-3"]["description"])
        self.assertEqual((self.lin.issues["ENG-4"]["status"], self.lin.issues["ENG-4"]["blockedBy"]), ("Todo", ["ENG-3"]))
        self.assertEqual(self.lin.issues["ENG-5"]["status"], "Canceled")
        self.assertEqual(self.lin.issues["ENG-1"]["description"], MAP)
        self.assertEqual(self.git("rev-parse", "fast/hw/003"), old)
        self.assertEqual(fc.load_change(self.proj, "C2")["why"], "undo C1")
        self.assertIn("C2 open: undo C1", out)

    def test_undo_refuses_when_something_it_touched_moved_since(self):
        synced(self.proj, MAP_AFTER, dict(AFTER, **{"ENG-3": issue("003", "Save to the server, batched.")}), ahead=3)
        with self.assertRaises(SystemExit) as e:
            change(self.proj, self.repo, "undo", cid="C1")
        self.assertIn("003", str(e.exception))
        self.assertIsNone(fc.open_change(self.proj))

    def test_without_a_key_it_prints_the_edits(self):
        with mock.patch.object(fc, "LINEAR_KEY", None):
            out = change(self.proj, self.repo, "undo", cid="C1")
        self.assertIn("apply these through Linear (save_issue), then sync:", out)
        self.assertIn('ENG-4: {"status": "Todo", "blockedBy": ["ENG-3"]}', out)
        self.assertEqual(self.lin.issues["ENG-4"]["status"], "Canceled")  # nothing was written
        self.assertEqual(fc.open_change(self.proj), "C2")

    def test_linear_failing_midway_lists_what_is_left_and_leaves_the_undo_open(self):
        self.lin.fail_on = "ENG-3"
        out = change(self.proj, self.repo, "undo", cid="C1")
        self.assertEqual(self.lin.issues["ENG-5"]["status"], "Canceled")  # applied before the failure
        self.assertIn("  ENG-3: ", out)
        self.assertIn("  ENG-1: ", out)
        self.assertNotIn("  ENG-5: ", out)
        self.assertEqual(fc.open_change(self.proj), "C2")

    def test_a_branch_git_refuses_to_move_is_listed_and_the_undo_still_finishes(self):
        tip = self.git("rev-parse", "refs/fast-coding/hw/C1/003")
        self.git("worktree", "add", str(Path(tempfile.mkdtemp()) / "wt"), "fast/hw/003")  # checked out elsewhere: `branch -f` refuses
        out = change(self.proj, self.repo, "undo", cid="C1")
        self.assertIn("reset these branches by hand, then sync:", out)
        self.assertIn(f"  git branch -f fast/hw/003 {tip}", out)
        self.assertEqual(self.lin.issues["ENG-4"]["status"], "Todo")  # the Linear step still ran
        self.assertIn("C2 open: undo C1", out)
        self.assertEqual(fc.open_change(self.proj), "C2")

    def test_blockers_are_set_to_exactly_the_snapshot(self):
        self.lin.issues["ENG-4"]["blockedBy"] = ["ENG-3", "ENG-5"]
        fc.linear_blocked_by(fc.linear_issue("ENG-4"), ["ENG-3"])
        self.assertEqual(self.lin.issues["ENG-4"]["blockedBy"], ["ENG-3"])


class ChangeBrief(unittest.TestCase):
    def setUp(self):
        self.proj = project()
        self.repo, _ = git_repo(())
        p = mock.patch.object(fc, "say", lambda m: None); p.start(); self.addCleanup(p.stop)
        synced(self.proj, MAP, BEFORE)

    def brief(self, cid, extra=None):
        out = io.StringIO()
        with mock.patch.object(fc, "project_dir", lambda a: self.proj), mock.patch.object(fc, "project_worktree", lambda p: self.repo), \
                redirect_stdout(out):
            fc.cmd_wayfinder(SimpleNamespace(extra=extra, change=cid))
        return out.getvalue()

    def test_the_change_wayfinder_asks_on_its_own_page(self):
        change(self.proj, self.repo, "start", why="localStorage is wiped by the sandbox")
        brief = self.brief("C1", extra="held: 003, 004")
        page = str(self.proj / "lavish" / "change-C1.html")
        self.assertIn(f"npx -y lavish-axi poll {page}", brief)
        self.assertIn("localStorage is wiped by the sandbox", brief)
        self.assertIn("- ~~<old line>~~ (C1)", brief)
        self.assertIn('"keep it as is"', brief)
        self.assertIn("Do not touch tasks, stories, or the plan", brief)
        self.assertTrue(brief.rstrip().endswith("held: 003, 004"))

    def test_only_an_open_change_gets_a_brief(self):
        with self.assertRaises(SystemExit):
            self.brief("C9")


if __name__ == "__main__":
    unittest.main()
