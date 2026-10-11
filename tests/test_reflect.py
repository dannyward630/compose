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


if __name__ == "__main__":
    unittest.main()
