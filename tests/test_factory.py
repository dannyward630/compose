import hermetic  # first: no test sees the real home
import os, subprocess, tempfile, unittest
from pathlib import Path
import importlib.machinery, importlib.util, sys
# tests/test_modules.py fails a test file without the next line
os.environ["HERDR_ENV"] = ""
_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)
import fc_factorystate as st


class State(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory(); self.addCleanup(d.cleanup)
        self.repo = Path(d.name).resolve()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)

    def test_state_round_trips_and_events_are_numbered(self):
        self.assertEqual(st.load_state(self.repo), st.EMPTY)
        s = st.load_state(self.repo); s["dispatched"]["NEB-10"] = {"feature": "NEB-9"}; st.save_state(self.repo, s)
        self.assertEqual(st.load_state(self.repo)["dispatched"], {"NEB-10": {"feature": "NEB-9"}})
        self.assertEqual(st.state_path(self.repo), self.repo / ".compose" / "factory.json")
        self.assertEqual([st.add_event(self.repo, f"event factory=x n={i}") for i in range(3)], [1, 2, 3])
        self.assertEqual([e["line"] for e in st.events_since(self.repo, 1)], ["event factory=x n=1", "event factory=x n=2"])

    def test_unreadable_state_reads_as_empty(self):
        st.state_path(self.repo).parent.mkdir(exist_ok=True); st.state_path(self.repo).write_text("{not json")
        self.assertEqual(st.load_state(self.repo), st.EMPTY)

    def test_saved_values_of_the_wrong_type_are_ignored(self):
        st.state_path(self.repo).parent.mkdir(exist_ok=True)
        st.state_path(self.repo).write_text('{"dispatched": null, "said": [], "mode": ["x"], "day_tickets": 3, "pid": 7}')
        s = st.load_state(self.repo)
        self.assertEqual((s["dispatched"], s["said"], s["mode"], s["day_tickets"], s["pid"]), ({}, {}, "day", 3, 7))
        st.state_path(self.repo).write_text("[1]")
        self.assertEqual(st.load_state(self.repo), st.EMPTY)

    def test_corrupt_event_lines_are_skipped_and_a_torn_line_is_not_glued_onto(self):
        st.events_path(self.repo).parent.mkdir(exist_ok=True)
        good = '{"n": 4, "at": 1.0, "line": "kept"}'
        st.events_path(self.repo).write_text("null\n[]\n{}\n" + '{"x":1}\n' + good + '\n{"n": 9, "at"')
        self.assertEqual([e["n"] for e in st.events_since(self.repo, 0)], [4])
        self.assertEqual(st.add_event(self.repo, "next"), 5)
        self.assertEqual([e["line"] for e in st.events_since(self.repo, 4)], ["next"])

    def test_day_pace_is_the_repos_setting_else_the_config(self):
        s = st.load_state(self.repo); self.assertEqual(st.pace(s), {"mode": "day", "cap": 2})
        s["day_tickets"] = 1; self.assertEqual(st.pace(s), {"mode": "day", "cap": 1})

    def test_say_once_repeats_nothing_until_the_line_changes(self):
        s, out = st.load_state(self.repo), []
        for line in ("a", "a", "b"): st.say_once(s, "k", line, out)
        self.assertEqual(out, ["a", "b"])


if __name__ == "__main__":
    unittest.main()
