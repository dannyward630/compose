import importlib.machinery, importlib.util, io, json, os, sys, tempfile, time, unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock
os.environ["FAST_CODING_NO_TREEHOUSE"] = "1"

BIN = Path(__file__).resolve().parents[1] / "bin"
sys.path.insert(0, str(BIN))
import fc_cost, fc_sessions  # noqa: E402

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(BIN / "fast_coding.py")))
fc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fc)

START = "2026-10-17 09:05:00"


def ts(delta=0):
    t = time.mktime(time.strptime(START, "%Y-%m-%d %H:%M:%S")) + delta
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def user(text, delta=0):
    return {"type": "user", "timestamp": ts(delta), "message": {"role": "user", "content": text}}


def asst(mid, model="claude-sonnet-5-5", **u):
    return {"type": "assistant", "timestamp": ts(5), "message": {"id": mid, "model": model, "usage": u}}


def write(path, lines, mtime=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join((x if isinstance(x, str) else json.dumps(x)) + "\n" for x in lines))
    if mtime:
        os.utime(path, (mtime, mtime))


class SessionUsage(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        p = mock.patch("pathlib.Path.home", return_value=self.home)
        p.start()
        self.addCleanup(p.stop)

    def test_log_dir_slug(self):
        self.assertEqual(fc_sessions.log_dir("/Users/a/.x/b"), self.home / ".claude" / "projects" / "-Users-a--x-b")
        self.assertEqual(fc_sessions.log_dir(Path("/a_b c/é9")), self.home / ".claude" / "projects" / "-a-b-c--9")

    def test_usage_counts_each_id_once_and_skips_bad_lines(self):
        big = dict(input_tokens=2, cache_creation_input_tokens=28939, cache_read_input_tokens=7634, output_tokens=4)
        log = self.home / "s.jsonl"
        write(log, [user("hi"), asst("m1", **big), {"type": "summary"}, asst("m1", **big),
                    asst("m2", "claude-opus-5-5", input_tokens=10, output_tokens=7), '{"type": "assistant", "mess'])
        self.assertEqual(fc_sessions.usage(str(log)), {"model": "claude-sonnet-5-5", "turns": 2, "input": 12,
                                                       "cache_created": 28939, "cache_read": 7634, "output": 11})
        write(log, [user("hi"), "not json"])
        self.assertEqual(fc_sessions.usage(log), {"model": None, "turns": 0, "input": 0, "cache_created": 0, "cache_read": 0, "output": 0})

    def test_find_session_by_brief_and_start(self):
        cwd = "/w/.t/x"
        self.assertIsNone(fc_sessions.find_session(cwd, START, "/p/a.brief.md"))
        d, now = fc_sessions.log_dir(cwd), time.time()
        write(d / "a_old.jsonl", [user("Your brief is the file /p/a.brief.md.", -121)], now - 35)
        write(d / "a.jsonl", [user("Your brief is the file /p/a.brief.md.", -60), asst("m1")], now - 40)
        write(d / "b.jsonl", [user([{"type": "text", "text": "Your brief is the file /p/b.brief.md."}], 30)], now - 30)
        write(d / "later.jsonl", [user("other", 40), user("/p/a.brief.md", 41)], now - 20)
        self.assertEqual(fc_sessions.find_session(cwd, START, "/p/a.brief.md"), d / "a.jsonl")
        self.assertEqual(fc_sessions.find_session(Path(cwd), START, Path("/p/b.brief.md")), d / "b.jsonl")
        self.assertIsNone(fc_sessions.find_session(cwd, START, "/p/c.brief.md"))
        write(d / "a2.jsonl", [user("Your brief is the file /p/a.brief.md.", 50)], now - 10)
        self.assertEqual(fc_sessions.find_session(cwd, START, "/p/a.brief.md"), d / "a2.jsonl")


def project():
    proj = Path(tempfile.mkdtemp())
    crew = proj / "results" / "crew"
    crew.mkdir(parents=True)
    for name, role, model, at in [("a-late", "planner", "claude:claude-opus-5-5", "2026-10-17 09:00:00"),
                                  ("z-early", "implementer", "pi:openai/gpt-6-astra", "2026-10-17 08:00:00")]:
        (crew / (name + ".json")).write_text(json.dumps({"name": name, "role": role, "model": model, "cwd": str(proj), "started_at": at}))
        (crew / (name + ".brief.md")).write_text("brief")
    (crew / "stray.json").write_text(json.dumps({"x": 1}))
    run = {"pi:openrouter/x": {"calls": 3, "tokens_in": 1200, "tokens_out": 300, "cost": 0.01, "priced": True},
           "typesafe": {"calls": 1, "tokens_in": 50, "tokens_out": 7, "cost": 0.0, "priced": False}, "total": 0.01}
    (proj / "results" / "run-cost.json").write_text(json.dumps(run))
    return proj


class CostRows(unittest.TestCase):
    def setUp(self):
        self.proj = project()
        log = self.proj / "a.jsonl"
        found = lambda cwd, at, brief: log if Path(brief).name == "a-late.brief.md" else None  # noqa: E731
        use = {"model": "claude-opus-5-5", "turns": 4, "input": 10, "cache_created": 200, "cache_read": 3000, "output": 40}
        self.find = mock.patch.object(fc_sessions, "find_session", side_effect=found).start()
        mock.patch.object(fc_sessions, "usage", return_value=use).start()
        self.addCleanup(mock.patch.stopall)
        self.rows = fc_cost.rows(self.proj)

    def test_rows(self):
        r = self.rows
        self.assertEqual([x["name"] for x in r[:2]], ["z-early", "a-late"])
        self.assertEqual({k: r[0][k] for k in ("role", "turns", "input", "cache_created", "cache_read", "output", "note")},
                         {"role": "implementer", "turns": None, "input": None, "cache_created": None, "cache_read": None, "output": None, "note": "no session log"})
        self.assertEqual({k: r[1][k] for k in ("turns", "input", "cache_created", "cache_read", "output", "note")},
                         {"turns": 4, "input": 10, "cache_created": 200, "cache_read": 3000, "output": 40, "note": ""})
        brief = self.proj / "results" / "crew" / "a-late.brief.md"
        self.assertIn((str(self.proj), "2026-10-17 09:00:00", brief), [(str(c.args[0]), c.args[1], Path(c.args[2])) for c in self.find.call_args_list])
        run = {x["name"]: x for x in r[2:]}
        self.assertEqual(len(r), 4)
        self.assertEqual({k: run["pi:openrouter/x"][k] for k in ("role", "turns", "input", "cache_created", "cache_read", "output")},
                         {"role": "run", "turns": 3, "input": 1200, "cache_created": 0, "cache_read": 0, "output": 300})
        self.assertEqual(run["typesafe"]["output"], 7)

    def test_total(self):
        t = fc_cost.total(self.rows)
        self.assertEqual((t["input"], t["cache_created"], t["cache_read"], t["output"], t["teammates"]), (1260, 200, 3000, 347, 2))

    def test_render(self):
        lines = fc_cost.render(self.rows).splitlines()
        self.assertEqual(len(lines), len(self.rows) + 2)
        self.assertTrue(lines[-1].startswith("total"))
        col = lines[0].index("role")
        for row, line in zip(self.rows, lines[1:-1]):
            self.assertEqual(line.index(row["role"], len(row["name"])), col, line)
        self.assertIn(" - ", lines[1])

    def test_empty(self):
        self.assertEqual(fc_cost.rows(Path(tempfile.mkdtemp())), [])
        self.assertEqual(fc_cost.render([]).strip(), "cost  none")


if __name__ == "__main__":
    unittest.main()
