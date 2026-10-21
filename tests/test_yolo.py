import hermetic  # first: no test sees the real home
import contextlib, importlib.machinery, importlib.util, io, json, os, sys, tempfile, time, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
os.environ["HERDR_ENV"] = ""

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)

ORCH = "hw-orchestrator"
stamp = lambda: time.strftime("%Y-%m-%d %H:%M:%S")


def snap(tasks=None, crew=None, verify=None, halt=None):
    return {"tasks": {tid: {"state": st, "attempts": 1, "cost": 0.0, "note": "", "linear": "", "title": f"task {tid}"}
                      for tid, st in (tasks or {}).items()},
            "agents": {}, "crew": crew or {}, "run": False, "crashed": False, "verify": verify, "halt": halt, "run_end": 0, "last": [0, ""]}


class Yolo(unittest.TestCase):
    """Yolo is a posture in a file: who answers a product-owner decision while they are away, and what they read on return."""
    def setUp(self):
        self.proj = Path(tempfile.mkdtemp()) / "hw"
        (self.proj / "results").mkdir(parents=True)
        self.file = self.proj / "results" / "yolo.json"

    def yolo(self, *words, push=False, clear_words=False, snapshot=None, pane="w1:p1"):
        """Run as the engineering manager session in herdr pane `pane`."""
        out = io.StringIO()
        a = SimpleNamespace(repo=".", project="hw", push=push, clear_words=clear_words, words=list(words))
        env = {k: v for k, v in os.environ.items() if k not in ("COMPOSE_ROLE", "HERDR_PANE_ID")} | {"HERDR_PANE_ID": pane}
        with mock.patch.object(fc.fc_core, "project_dir", return_value=self.proj), mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(fc.fc_watch, "watch_snapshot", return_value=snapshot or snap()), \
                mock.patch.object(fc.fc_worktree, "stack_order", return_value=[]), \
                mock.patch.object(fc.fc_cost, "rows", return_value=[]), contextlib.redirect_stdout(out):
            fc.fc_yolo.cmd_yolo(a)
        return out.getvalue()

    def test_entry_writes_the_file_and_reads_the_words_back(self):
        out = self.yolo("use", "Stripe;", "skip", "the", "design", "review", push=True)
        d = json.loads(self.file.read_text())
        self.assertEqual(d["words"], "use Stripe; skip the design review")
        self.assertTrue(d["push"])
        self.assertEqual(d["decisions"], [])
        self.assertTrue(d["since"])
        self.assertIn("use Stripe; skip the design review", out)
        self.assertIn("push: yes", out)
        self.assertIn("never pre-authorizable whatever the words say", out)
        self.assertIn("force-push", out)
        self.assertNotIn(chr(0x2014), out)

    def test_reentry_replaces_the_words_and_keeps_since_and_decisions(self):
        self.yolo("first")
        d = json.loads(self.file.read_text())
        d["since"] = "2026-01-01 09:00:00"
        d["decisions"] = [{"ts": "2026-01-01 09:30:00", "text": "db?: postgres"}]
        self.file.write_text(json.dumps(d))
        out = self.yolo("second")
        d = json.loads(self.file.read_text())
        self.assertEqual((d["since"], d["words"], len(d["decisions"])), ("2026-01-01 09:00:00", "second", 1))
        self.assertIn("push: no", out)

    def test_clear_words_empties_them_and_keeps_since_push_and_decisions(self):
        self.yolo("ship", push=True)
        self.yolo("decided", "db?: postgres")
        since = json.loads(self.file.read_text())["since"]
        out = self.yolo(clear_words=True)
        d = json.loads(self.file.read_text())
        self.assertEqual((d["words"], d["since"], d["push"], [x["text"] for x in d["decisions"]]), ("", since, True, ["db?: postgres"]))
        self.assertIn("words cleared", out)
        for words, push in ((["new"], False), ([], True)):
            with self.assertRaises(SystemExit):
                self.yolo(*words, push=push, clear_words=True)
        self.assertEqual(json.loads(self.file.read_text()), d)

    def test_clear_words_without_yolo_exits_1(self):
        with self.assertRaises(SystemExit) as e:
            self.yolo(clear_words=True)
        self.assertEqual(e.exception.code, 1)
        self.assertFalse(self.file.exists())

    def test_words_that_look_like_a_command_are_refused_with_a_quoting_hint(self):
        self.yolo("ship", "it", push=True)
        d = json.loads(self.file.read_text())
        for words in (["--project hw decided db?: postgres"], ["--repo . --project hw ship it"], ["decided --project hw db?: pg"],
                      ["db?", "decided", "postgres"]):
            with self.assertRaises(SystemExit) as e:
                self.yolo(*words)
            self.assertIn("quote", str(e.exception.code))
            self.assertIn('compose yolo decided --project hw "<question>: <answer taken>"', str(e.exception.code))
        self.assertEqual(json.loads(self.file.read_text()), d)
        self.yolo("the", "decidedly", "safe", "option")
        self.assertEqual(json.loads(self.file.read_text())["words"], "the decidedly safe option")

    def test_decided_appends(self):
        self.yolo()
        self.yolo("decided", "which db?: postgres, the recommendation")
        self.yolo("decided", "cards NEB-4:", "accept-all")
        d = json.loads(self.file.read_text())
        self.assertEqual([x["text"] for x in d["decisions"]], ["which db?: postgres, the recommendation", "cards NEB-4: accept-all"])
        self.assertTrue(all(x["ts"] for x in d["decisions"]))

    def test_off_prints_the_digest_from_disk_then_archives(self):
        self.yolo("go", "with", "Stripe")
        d = json.loads(self.file.read_text())
        d["since"] = "2026-01-01 09:00:00"
        self.file.write_text(json.dumps(d))
        self.yolo("decided", "provider?: Stripe")
        for tid in ("001", "002", "003"):
            (self.proj / "results" / f"{tid}.json").write_text("{}")
        crew = {ORCH: [{"at": "2025-12-31 10:00:00", "state": "needs-user", "message": "before yolo"},
                       {"at": stamp(), "state": "needs-user", "message": "delete prod data?"}],
                "hw-q": [{"at": stamp(), "state": "blocked", "message": "answered later"},
                         {"at": stamp(), "state": "working", "message": "going again"}]}
        s = snap(tasks={"001": "passed", "002": "failed", "003": "rejected_size"}, crew=crew,
                 verify=[int(time.time()), False], halt=["2026-01-01 10:00:00", "openrouter", 2])
        out = self.yolo("off", snapshot=s)
        heads = ["Your instructions", "Decided for you", "To confirm", "Waiting on you", "Tried and failed", "Done", "Cost"]
        pos = [out.index(h) for h in heads]
        self.assertEqual(pos, sorted(pos), out)
        sec = lambda h: out.split(h, 1)[1].split(heads[heads.index(h) + 1], 1)[0] if h != "Cost" else out.split(h, 1)[1]
        self.assertIn("go with Stripe", sec("Your instructions"))
        self.assertIn("provider?: Stripe", sec("Decided for you"))
        self.assertIn("(yolo recommendation, unconfirmed, <date>)", sec("To confirm"))
        self.assertIn("1 decision(s)", sec("To confirm"))
        waiting = sec("Waiting on you")
        self.assertIn("delete prod data?", waiting)
        self.assertNotIn("before yolo", waiting)
        self.assertNotIn("answered later", waiting)
        self.assertIn("openrouter", waiting)
        self.assertIn("verify FAIL", waiting)
        failed = sec("Tried and failed")
        self.assertIn("002", failed)
        self.assertIn("003", failed)
        self.assertNotIn("001", failed)
        self.assertIn("001", sec("Done"))
        self.assertFalse(self.file.exists())
        self.assertTrue((self.proj / "results" / "yolo-2026-01-01T090000.json").exists())

    def test_off_with_no_decisions_has_nothing_to_confirm(self):
        self.yolo("go")
        out = self.yolo("off")
        self.assertEqual(out.split("To confirm", 1)[1].split("Waiting on you", 1)[0].split(), ["-", "none"])

    def test_decided_prints_the_yolo_form_that_tags_the_map_line(self):
        self.yolo("go")
        out = self.yolo("decided", "which db?: postgres")
        self.assertIn("`yolo: <card id>: <answer>`", out)
        self.assertIn(f"(yolo recommendation, unconfirmed, {time.strftime('%Y-%m-%d')})", out)
        self.assertIn("never as the product owner's", out)

    def test_off_and_decided_without_yolo_exit_1(self):
        for words in (["off"], ["decided", "x: y"]):
            with self.assertRaises(SystemExit) as e:
                self.yolo(*words)
            self.assertEqual(e.exception.code, 1)

    def test_manager_attention_stays_silent_for_needs_user_and_fires_for_blocked(self):
        self.yolo()
        calls = []
        ev = [f"event crew={ORCH} state=needs-user message='Stripe or Adyen? I recommend Stripe'"]
        env = {k: v for k, v in os.environ.items() if k != "COMPOSE_ROLE"}
        with mock.patch.object(fc.fc_crew, "desktop_notify", lambda *args: calls.append(args)), mock.patch.dict(os.environ, env, clear=True):
            fc.fc_crew.manager_attention(self.proj, ev)
            self.assertEqual(calls, [])
            fc.fc_crew.manager_attention(self.proj, [f"event crew={ORCH} state=blocked message='no key'"])
        self.assertEqual(calls, [("hw: the engineering manager is blocked", f"no key  (from {ORCH})")])

    def watch_now(self, s, pane="w1:p1"):
        """`watch --now` as the engineering manager session in herdr pane `pane`."""
        out = []
        a = SimpleNamespace(repo=".", project="hw", now=True, from_=None, timeout=0, interval=0.01, stall=10_000)
        env = {k: v for k, v in os.environ.items() if k not in ("COMPOSE_ROLE", "HERDR_PANE_ID")} | {"HERDR_PANE_ID": pane}
        with mock.patch.object(fc.fc_core, "project_dir", return_value=self.proj), mock.patch.object(fc.fc_watch, "watch_snapshot", return_value=s), \
                mock.patch("builtins.print", out.append), mock.patch.dict(os.environ, env, clear=True):
            fc.fc_watch.cmd_watch(a)
        return out

    def test_watch_now_prints_yolo_first_and_marks_needs_user(self):
        self.assertFalse(any("yolo" in line for line in self.watch_now(snap())))
        self.yolo("ship", "it", push=True)
        out = self.watch_now(snap(crew={"hw-q": [{"at": stamp(), "state": "needs-user", "message": "db?"}]}))
        self.assertTrue(out[0].startswith("event yolo=on push=yes since="), out)
        self.assertIn("by='this session'", out[0])
        self.assertIn("words='ship it'", out[0])
        line = next(l for l in out if "state=needs-user" in l)
        self.assertTrue(line.endswith("  yolo=on (answer with the recommendation; log it: compose yolo decided ...)"), line)

    def test_another_session_sees_who_set_yolo(self):
        """yolo is per project: a second engineering manager session on it is told the posture is not its own."""
        self.yolo("ship", "it", pane="w1:p2")
        self.assertEqual(json.loads(self.file.read_text())["by"], {"role": "manager", "session": "w1:p2"})
        out = self.watch_now(snap(crew={"hw-q": [{"at": stamp(), "state": "needs-user", "message": "db?"}]}), pane="w1:p1")
        self.assertIn("by='an engineering manager session in herdr pane w1:p2'", out[0])
        line = next(l for l in out if "state=needs-user" in l)
        self.assertTrue(line.endswith("  yolo=on set by an engineering manager session in herdr pane w1:p2 (answer with the recommendation; "
                                      "log it: compose yolo decided ...)"), line)

    def test_status_shows_the_header(self):
        self.yolo(push=True)
        d = json.loads(self.file.read_text())
        since = d["since"]
        self.file.write_text(json.dumps(d | {"mode": "yolo"}))
        with mock.patch.object(fc.fc_tasks, "load_tasks", return_value=[]), mock.patch.object(fc.fc_core, "current_branch", return_value="main"), \
                mock.patch.object(fc.fc_core, "sh", return_value=SimpleNamespace(stdout="abc\n", returncode=0)), \
                mock.patch.object(fc.fc_worktree, "stack_order", return_value=[]), mock.patch.object(fc.fc_cost, "rows", return_value=[]):
            lines = fc.fc_status.render_status(Path("."), [self.proj]).splitlines()
            self.assertIn(f"  yolo on (push) since {since}, set by an engineering manager session in herdr pane w1:p1", lines)  # the status tab is no session's
            self.file.write_text(json.dumps({"since": since, "push": False, "words": "", "decisions": []}))  # from before `by` was recorded
            lines = fc.fc_status.render_status(Path("."), [self.proj]).splitlines()
        self.assertIn(f"  away on since {since}", lines)

    def test_help_and_docs_list_yolo(self):
        root = Path(__file__).resolve().parents[1]
        self.assertIn("| `yolo", (root / "docs" / "cli.md").read_text())
        cmd = (root / "commands" / "yolo.md").read_text()
        self.assertIn("allowed-tools: Bash(compose yolo:*)", cmd)
        out = io.StringIO()
        with mock.patch.object(sys, "argv", ["compose", "--help"]), contextlib.redirect_stdout(out), contextlib.suppress(SystemExit):
            fc.main()
        self.assertIn("yolo", out.getvalue())

    def test_main_parses_decided_after_the_project_flag(self):
        seen = []
        with mock.patch.object(sys, "argv", ["compose", "yolo", "decided", "--project", "hw", "db?: postgres"]), \
                mock.patch.object(fc.fc_yolo, "cmd_yolo", seen.append), mock.patch.object(fc.fc_config, "apply_config", return_value="default"):
            fc.main()
        self.assertEqual(seen[0].words, ["decided", "db?: postgres"])

    def test_main_parses_clear_words_as_a_flag(self):
        seen = []
        with mock.patch.object(sys, "argv", ["compose", "yolo", "--project", "hw", "--clear-words"]), \
                mock.patch.object(fc.fc_yolo, "cmd_yolo", seen.append), mock.patch.object(fc.fc_config, "apply_config", return_value="default"):
            fc.main()
        self.assertEqual((seen[0].clear_words, seen[0].words), (True, []))


class StatusNamesPosture(unittest.TestCase):
    """The posture file's mode, `away` or `yolo`, is what `yolo_state` and `compose status` name; a file without one reads as away."""
    SINCE = "2026-01-01 09:00:00"

    def setUp(self):
        self.proj = Path(tempfile.mkdtemp()) / "hw"
        (self.proj / "results").mkdir(parents=True)
        self.file = self.proj / "results" / "yolo.json"

    def write(self, **extra):
        self.file.write_text(json.dumps({"since": self.SINCE, "push": False, "words": "", "decisions": []} | extra))

    def status(self):
        with mock.patch.object(fc.fc_tasks, "load_tasks", return_value=[]), mock.patch.object(fc.fc_core, "current_branch", return_value="main"), \
                mock.patch.object(fc.fc_core, "sh", return_value=SimpleNamespace(stdout="abc\n", returncode=0)), \
                mock.patch.object(fc.fc_worktree, "stack_order", return_value=[]), mock.patch.object(fc.fc_cost, "rows", return_value=[]):
            return fc.fc_status.render_status(Path("."), [self.proj]).splitlines()

    def test_yolo_state_fills_away_and_keeps_a_stored_mode(self):
        self.write()
        self.assertEqual(fc.fc_tasks.yolo_state(self.proj)["mode"], "away")
        for mode in ("away", "yolo"):
            self.write(mode=mode)
            self.assertEqual(fc.fc_tasks.yolo_state(self.proj)["mode"], mode)
        self.assertEqual(fc.fc_tasks.yolo_state(self.proj)["since"], self.SINCE)

    def test_yolo_state_is_none_for_a_missing_or_unreadable_file(self):
        self.assertIsNone(fc.fc_tasks.yolo_state(self.proj))
        self.file.write_text("{not json")
        self.assertIsNone(fc.fc_tasks.yolo_state(self.proj))

    def test_status_names_yolo_with_push_and_who(self):
        self.write(mode="yolo", push=True, by={"role": "manager", "session": "w1:p1"})
        self.assertIn(f"  yolo on (push) since {self.SINCE}, set by an engineering manager session in herdr pane w1:p1", self.status())

    def test_status_names_away_for_a_file_without_mode_or_by(self):
        self.write()
        self.assertIn(f"  away on since {self.SINCE}", self.status())

    def test_status_names_away_with_push_and_who_for_a_stored_mode(self):
        self.write(mode="away", push=True, by={"role": "manager", "session": "w1:p1"})
        self.assertIn(f"  away on (push) since {self.SINCE}, set by an engineering manager session in herdr pane w1:p1", self.status())

    def test_status_says_nothing_when_no_posture_is_on(self):
        self.assertFalse([l for l in self.status() if l.startswith(("  away on", "  yolo on"))])


if __name__ == "__main__":
    unittest.main()
