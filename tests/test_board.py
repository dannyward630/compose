import hermetic  # first: no test sees the real home
import importlib.machinery, importlib.util, json, os, subprocess, sys, tempfile, time, unittest
from pathlib import Path
from unittest import mock
os.environ["COMPOSE_NO_TREEHOUSE"] = "1"
os.environ["HERDR_ENV"] = ""

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)

ENV = {"HERDR_ENV": "", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


class Board(unittest.TestCase):
    """`status` and `watch` read the board every two seconds, from many loops at once: it must cost no process while nothing changed."""

    def setUp(self):
        self.env = mock.patch.dict(os.environ, ENV); self.env.start(); self.addCleanup(self.env.stop)
        self.repo = Path(tempfile.mkdtemp())
        self.git("init", "-q", "-b", "main")
        (self.repo / "a.txt").write_text("base\n")
        self.git("add", "-A"); self.git("commit", "-qm", "init")
        self.git("checkout", "-q", "-b", "compose/p")
        self.proj = self.repo / ".compose" / "p"
        (self.proj / "results").mkdir(parents=True)
        (self.proj / "verify.json").write_text(json.dumps({"task_prefix": "compose/p-"}))
        (self.repo / ".git" / "info" / "exclude").write_text("/.compose/\n")
        self.tasks(["001", "002", "003"])
        # 001: a branch merged into the project branch; 002: a branch not merged; 003: no branch yet
        self.git("checkout", "-q", "-b", "compose/p-001"); self.git("commit", "-q", "--allow-empty", "-m", "001")
        self.git("checkout", "-q", "compose/p"); self.git("merge", "-q", "compose/p-001")
        self.git("checkout", "-q", "-b", "compose/p-002"); self.git("commit", "-q", "--allow-empty", "-m", "002")
        self.git("checkout", "-q", "compose/p")
        self.result("001", "passed"); self.result("002", "passed")

    def git(self, *a):
        return subprocess.run(["git", *a], cwd=self.repo, check=True, capture_output=True, text=True).stdout.strip()

    def tasks(self, ids):
        (self.proj / "results" / "tasks.json").write_text(json.dumps({"feature": {}, "tasks": [{"id": i, "title": f"t{i}"} for i in ids]}))

    def result(self, tid, status, **kv):
        (self.proj / "results" / f"{tid}.json").write_text(json.dumps({"status": status, **kv}))

    def states(self, board):
        return {r["id"]: r["state"] for r in board["rows"]}

    def counting(self):
        """fc_core.sh wrapped so the test can count the processes a board read spawns."""
        return mock.patch.object(fc.fc_core, "sh", wraps=fc.fc_core.sh)

    def test_the_board_tells_each_tasks_state_from_the_branches(self):
        b = fc.fc_status.board(self.repo, self.proj)
        self.assertEqual(self.states(b), {"001": "merged", "002": "passed", "003": "pending"})
        self.assertEqual([r["note"] for r in b["rows"]], ["", "compose/p-002", ""])
        self.assertEqual(b["trunk"], "compose/p")
        self.assertEqual(b["layers"], {"compose/p-002": 1})

    def test_the_board_costs_no_process_while_nothing_changed(self):
        with self.counting() as sh:
            first = fc.fc_status.board(self.repo, self.proj)
            n = sh.call_count
            self.assertGreater(n, 0)
            self.assertEqual(fc.fc_status.board(self.repo, self.proj), first)
            self.assertEqual(sh.call_count, n, "a second read with nothing changed ran git")

    def test_the_boards_git_cost_does_not_grow_with_the_task_count(self):
        self.tasks([f"{i:03}" for i in range(1, 25)])
        with self.counting() as sh:
            fc.fc_status.board(self.repo, self.proj)
            self.assertLessEqual(sh.call_count, 6, [c.args[0] for c in sh.call_args_list])

    def test_a_new_branch_changes_the_board(self):
        fc.fc_status.board(self.repo, self.proj)
        self.git("checkout", "-q", "-b", "compose/p-003"); self.git("commit", "-q", "--allow-empty", "-m", "003"); self.git("checkout", "-q", "compose/p")
        self.assertEqual(self.states(fc.fc_status.board(self.repo, self.proj))["003"], "pending")
        self.result("003", "passed")
        self.assertEqual(self.states(fc.fc_status.board(self.repo, self.proj))["003"], "passed")
        self.git("merge", "-q", "compose/p-003")
        self.assertEqual(self.states(fc.fc_status.board(self.repo, self.proj))["003"], "merged")

    def test_a_result_written_by_another_process_changes_the_board(self):
        fc.fc_status.board(self.repo, self.proj)
        time.sleep(0.01)
        self.result("003", "running", attempts=1)
        (self.proj / "results" / "run.json").write_text(json.dumps({"pid": os.getpid(), "started_at": "2026-10-19 01:00:00"}))
        b = fc.fc_status.board(self.repo, self.proj)
        self.assertEqual(self.states(b)["003"], "running")
        self.assertEqual(b["rows"][2]["attempts"], 1)

    def test_a_run_that_died_shows_without_any_file_changing(self):
        self.result("003", "running")
        gone = subprocess.run(["true"], capture_output=True)  # a pid that is no longer alive
        marker = self.proj / "results" / "run.json"
        marker.write_text(json.dumps({"pid": os.getpid(), "started_at": "2026-10-19 01:00:00"}))
        self.assertEqual(self.states(fc.fc_status.board(self.repo, self.proj))["003"], "running")
        with mock.patch.object(fc.fc_tasks, "pid_alive", return_value=False):
            self.assertEqual(self.states(fc.fc_status.board(self.repo, self.proj))["003"], "interrupted")

    def test_a_held_task_changes_the_board(self):
        fc.fc_status.board(self.repo, self.proj)
        time.sleep(0.01)
        (self.proj / "results" / "hold.json").write_text(json.dumps({"003": {"reason": "plan changes", "at": "x"}}))
        self.assertEqual(self.states(fc.fc_status.board(self.repo, self.proj))["003"], "held")

    def test_task_branches_runs_one_git_call(self):
        with self.counting() as sh:
            self.assertEqual(fc.fc_worktree.task_branches(self.repo, self.proj), {"compose/p-002": None})
            self.assertEqual(sh.call_count, 1, [c.args[0] for c in sh.call_args_list])

    def test_watch_snapshot_costs_no_process_while_nothing_changed(self):
        with mock.patch.object(fc.fc_herdr, "herdr", return_value=None), self.counting() as sh:
            first = fc.fc_watch.watch_snapshot(self.repo, self.proj)
            n = sh.call_count
            self.assertEqual(fc.fc_watch.watch_snapshot(self.repo, self.proj), first)
            self.assertEqual(sh.call_count, n)
        self.assertEqual({t: v["state"] for t, v in first["tasks"].items()}, {"001": "merged", "002": "passed", "003": "pending"})

    def test_a_watch_loop_asks_herdr_for_its_agents_once_per_interval(self):
        clock, agents = [1000.0], fc.fc_watch.Agents()
        with mock.patch.object(fc.fc_herdr, "herdr", return_value={"agents": [{"name": "p-orchestrator", "agent_status": "idle"}]}) as h, \
                mock.patch.object(fc.fc_watch.time, "monotonic", lambda: clock[0]):
            for _ in range(3):
                snap = fc.fc_watch.watch_snapshot(self.repo, self.proj, agents)
            self.assertEqual(snap["agents"], {"p-orchestrator": "idle"})
            self.assertEqual(h.call_count, 1)
            clock[0] += fc.fc_watch.AGENTS_INTERVAL + 1
            fc.fc_watch.watch_snapshot(self.repo, self.proj, agents)
            self.assertEqual(h.call_count, 2)
            fc.fc_watch.watch_snapshot(self.repo, self.proj)  # a one-off read, as `watch --now` does, asks every time
            self.assertEqual(h.call_count, 3)


if __name__ == "__main__":
    unittest.main()
