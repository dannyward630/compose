import hermetic  # first: no test sees the real home
import importlib.machinery, importlib.util, os, signal, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
os.environ["HERDR_ENV"] = ""   # tests/test_modules.py fails a test file without this line
_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)
import fc_crew, fc_load, fc_shed, fc_started
class ShedFree(unittest.TestCase):
    def setUp(self):
        p = subprocess.Popen([sys.executable, "-c", "pass"]); p.wait()
        self.dead, self.avg, self.recs, self.table, self.sigs, self.forgot, self.root = p.pid, 13.0, [], [], [], [], Path(tempfile.mkdtemp())
        (self.root / "old").mkdir(); (self.root / "proj").mkdir(); (self.root / "proj" / "verify.json").write_text("{}")  # "old" has none: that project ended
        def kill(pid, sig):
            if sig == 0 and pid == self.dead: raise ProcessLookupError
            if sig == signal.SIGTERM: self.sigs.append(pid)
        self.run, self.stop = mock.Mock(side_effect=lambda *a, **k: mock.Mock(returncode=0, stdout="".join(f"{p} {pp} {c} {cmd}\n" for p, pp, c, cmd in self.table))), mock.Mock(return_value=["999"])
        for p in (mock.patch("os.cpu_count", return_value=8), mock.patch("os.getloadavg", lambda: (self.avg,) * 3), mock.patch("time.time", return_value=1000.0), mock.patch("os.kill", kill),
                  mock.patch("subprocess.run", self.run), mock.patch.dict(os.environ), mock.patch.object(fc_crew, "stop_listeners_under", self.stop),
                  mock.patch.object(fc_started, "entries", lambda: self.recs), mock.patch.object(fc_started, "forget", self.forgot.append)):
            p.start(); self.addCleanup(p.stop)
        os.environ.pop("COMPOSE_NO_LOAD", None)
    def rec(self, pid, project=None, kind="test", **kw):
        self.recs.append({"pid": pid, "kind": kind, "project": project and str(self.root / project), "waiter": None, "until": None, "cwd": None, "at": 1.0, "alive": True, **kw})
    def pses(self):
        return [c for c in self.run.call_args_list if c.args[0][0] == "ps"]
    def test_each_freeable_kind_is_killed_with_its_tree_forgotten_and_named(self):
        self.rec(100, waiter=self.dead); self.rec(200, "old"); self.rec(300, "proj", until=900.0); self.rec(400, "proj", until=2000.0)
        self.table = [(100, 1, 0.0, "sh"), (101, 100, 0.0, "node"), (200, 1, 0.0, "sh"), (201, 200, 0.0, "node"), (300, 1, 0.0, "sh"), (301, 300, 0.0, "node"), (400, 1, 0.0, "sh")]
        lines = fc_shed.tick()
        self.assertEqual((sorted(self.sigs), sorted(self.forgot), len(self.pses())), ([100, 101, 200, 201, 300, 301], [100, 200, 300], 1))
        want = [(100, "-", "waiter gone"), (200, "old", "project ended"), (300, "proj", "past its limit")]
        self.assertEqual(sorted(l for l in lines if "shed=freed" in l), [f"event shed=freed pid={p} kind=test project={pr} why={w}" for p, pr, w in want])
        s = fc_shed.state()
        self.assertEqual((sorted(s["freed"], key=lambda e: e["pid"]), s["hold"]), ([{"pid": p, "kind": "test", "project": pr, "why": w, "at": 1000.0} for p, pr, w in want], {"n": 1, "at": 1000.0}))
    def test_live_waiter_verify_tree_and_foreign_process_are_never_killed(self):
        self.rec(100, "proj", waiter=os.getpid()); self.rec(200, waiter=self.dead)  # 200 is freeable, but its tree runs a verify
        self.table = [(100, 1, 0.0, "sh"), (101, 100, 0.0, "node"), (os.getpid(), 1, 0.0, "python"), (200, 1, 0.0, "sh"), (201, 200, 0.0, "/usr/local/bin/compose verify"), (900, 1, 90.0, "node x")]
        self.assertEqual((["shed=freed" in l for l in fc_shed.tick()], self.sigs, self.forgot, fc_shed.state()["freed"]), ([False], [], [], []))
    def test_hot_line_names_the_hottest_outside_recorded_trees_once_per_hold(self):
        self.rec(100, "proj", waiter=os.getpid())
        self.table = [(100, 1, 0.0, "sh"), (101, 100, 99.0, "busy"), (900, 1, 79.6, "/usr/bin/node server.js"), (901, 1, 5.0, "zsh")]
        line = "event shed=hot pid=900 cpu=80 command=node (not started by compose, left alone)"
        self.assertEqual((fc_shed.tick(), fc_shed.state()["hot"], fc_shed.tick()), ([line], {"pid": 900, "cpu": 79.6, "command": "node"}, []))
        self.avg = 7.0
        self.assertEqual((fc_shed.tick(), fc_shed.state()["hold"]), ([], None))
        self.avg = 13.0
        self.assertEqual(fc_shed.tick(), [line])
    def test_dead_record_is_forgotten_and_a_dead_teammates_dev_server_is_stopped_unless_a_live_one_shares_it(self):
        self.rec(100, kind="teammate", alive=False, cwd="/w/a"); self.rec(101, kind="teammate", alive=False, cwd="/w/b"); self.rec(102, "proj", kind="teammate", waiter=os.getpid(), cwd="/w/b")
        self.table = [(102, 1, 0.0, "claude")]
        lines = fc_shed.tick()
        self.stop.assert_called_once_with("/w/a")
        self.assertEqual((sorted(self.forgot), self.sigs, any("why=dev server of a done crew" in l for l in lines)), ([100, 101], [], True))
    def test_not_held_runs_no_ps_and_prints_nothing(self):
        self.rec(100, waiter=self.dead); self.table = [(100, 1, 0.0, "sh")]
        self.avg = 1.0
        self.assertEqual((fc_shed.tick(), self.pses(), self.sigs, self.forgot, fc_shed.state()), ([], [], [], [], {"hold": None, "freed": [], "hot": None, "paused": []}))
STOP, CONT = signal.SIGSTOP, signal.SIGCONT
def paused(pid, kind): return f"event shed=paused pid={pid} kind={kind} project=proj  (resumes in reverse once the load falls below 8.0)"
def resumed(pid, kind): return f"event shed=resumed pid={pid} kind={kind} project=proj"
class ShedPause(unittest.TestCase):
    def setUp(self):
        self.avg, self.now, self.sigs, root = 13.0, 1000.0, [], Path(tempfile.mkdtemp())
        (root / "proj").mkdir(); (root / "proj" / "verify.json").write_text("{}")
        self.recs = [{"pid": p, "kind": k, "project": str(root / "proj"), "waiter": os.getpid(), "until": None, "cwd": None, "at": float(a), "alive": True}
                     for p, k, a in ((200, "teammate", 2), (400, "teammate", 4), (100, "implementer", 1), (300, "test", 3))]  # 300 is the newest but a timed record: never paused
        self.table = [row for p in (100, 200, 300, 400) for row in ((p, 1, 0.0, "claude"), (p + 1, p, 0.0, "node"))]
        def kill(pid, sig):
            if sig in (STOP, CONT): self.sigs.append((pid, sig))
        run = mock.Mock(side_effect=lambda *a, **k: mock.Mock(returncode=0, stdout="".join(f"{p} {pp} {c} {cmd}\n" for p, pp, c, cmd in self.table)))
        for p in (mock.patch("os.cpu_count", return_value=8), mock.patch("os.getloadavg", lambda: (self.avg,) * 3), mock.patch("time.time", lambda: self.now), mock.patch("os.kill", kill),
                  mock.patch("subprocess.run", run), mock.patch.dict(os.environ), mock.patch.object(fc_started, "entries", lambda: self.recs),
                  mock.patch.object(fc.fc_herdr, "herdr"), mock.patch.object(fc_crew, "desktop_notify"), mock.patch.object(fc_load, "claim", return_value=True)):
            p.start(); self.addCleanup(p.stop)
        os.environ.pop("COMPOSE_NO_LOAD", None)
    def go(self, t, avg=13.0):
        self.now, self.avg, self.sigs[:] = t, avg, []
        return [l for l in fc_shed.tick() if "shed=paused" in l or "shed=resumed" in l], sorted(self.sigs)
    def test_newest_pauses_after_120s_then_one_a_minute_and_a_timed_record_never(self):
        got = [self.go(t) for t in (1000, 1119, 1130, 1180, 1195, 1250, 1260, 1400)]
        none = ([], [])
        self.assertEqual(got, [none, none, ([paused(400, "teammate")], [(400, STOP), (401, STOP)]), none, ([paused(200, "teammate")], [(200, STOP), (201, STOP)]), none,
                               ([paused(100, "implementer")], [(100, STOP), (101, STOP)]), none])
        s = fc_shed.state()
        self.assertEqual(([(e["pid"], e["kind"], e["project"], e["at"]) for e in s["paused"]], s["step_at"]), ([(400, "teammate", "proj", 1130.0), (200, "teammate", "proj", 1195.0), (100, "implementer", "proj", 1260.0)], 1260.0))
    def test_a_tree_running_verify_is_skipped_and_never_signalled(self):
        self.table[-1] = (401, 400, 0.0, "/usr/local/bin/compose verify")
        got = [self.go(t) for t in (1000, 1130, 1195, 1260)]
        self.assertEqual(got, [([], []), ([paused(200, "teammate")], [(200, STOP), (201, STOP)]), ([paused(100, "implementer")], [(100, STOP), (101, STOP)]), ([], [])])
    def test_resumes_in_reverse_with_the_tree_read_then_one_a_minute_and_only_below_low(self):
        for t in (1000, 1130, 1195): self.go(t)
        self.table = [r for r in self.table if r[0] not in (201, 401)] + [(202, 200, 0.0, "node"), (402, 400, 0.0, "node")]
        got = [self.go(1200, 7.0), self.go(1210, 10.0), self.go(1215, 7.0), self.go(1261, 7.0), self.go(1400, 7.0)]
        self.assertEqual(got, [([resumed(200, "teammate")], [(200, CONT), (202, CONT)]), ([], []), ([], []), ([resumed(400, "teammate")], [(400, CONT), (402, CONT)]), ([], [])])
        self.assertEqual(fc_shed.state()["paused"], [])
    def test_a_released_hold_restarts_the_120s(self):
        got = [self.go(t, a) for t, a in ((1000, 13.0), (1100, 7.0), (1150, 13.0), (1200, 13.0), (1275, 13.0))]
        self.assertEqual(got, [([], [])] * 4 + [([paused(400, "teammate")], [(400, STOP), (401, STOP)])])
