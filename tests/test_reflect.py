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


if __name__ == "__main__":
    unittest.main()
