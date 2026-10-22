import hermetic  # first: no test sees the real home
import argparse, importlib.machinery, importlib.util, json, os, shutil, subprocess, tempfile, unittest
from pathlib import Path
from unittest import mock
import sys
os.environ["COMPOSE_NO_TREEHOUSE"] = "1"
os.environ["HERDR_ENV"] = ""

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)

ENV = {"HERDR_ENV": "", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def unit(name, lines):
    return {"name": name, "commits": [], "lines": lines, "generated": {}}


class Grouping(unittest.TestCase):
    def names(self, units, budget):
        return [[u["name"] for u in g] for g in fc.fc_layers.group_units(units, budget)]

    def test_consecutive_units_fill_a_layer_up_to_the_budget_in_order(self):
        us = [unit("001", 100), unit("002", 150), unit("003", 50), unit("004", 1)]
        self.assertEqual(self.names(us, 300), [["001", "002", "003"], ["004"]])

    def test_a_task_bigger_than_the_budget_is_never_split_and_stands_alone(self):
        us = [unit("001", 10), unit("002", 500), unit("003", 10)]
        self.assertEqual(self.names(us, 300), [["001"], ["002"], ["003"]])

    def test_a_small_unit_does_not_jump_the_queue_to_fill_a_gap(self):
        us = [unit("001", 200), unit("002", 150), unit("003", 5)]
        self.assertEqual(self.names(us, 300), [["001"], ["002", "003"]])

    def test_lockfiles_are_generated_other_files_are_not(self):
        for f in ("bun.lock", "web/package-lock.json", "yarn.lock", "go.sum", "pnpm-lock.yaml"):
            self.assertTrue(fc.fc_worktree.GENERATED_RE.search(f), f)
        for f in ("src/lock.ts", "locksmith.py", "docs/bun.lock.md"):
            self.assertFalse(fc.fc_worktree.GENERATED_RE.search(f), f)

    def test_a_task_branch_does_not_count_its_lockfile_toward_the_limit(self):
        r = Path(tempfile.mkdtemp())
        git = lambda *a: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=r, check=True, capture_output=True)
        git("init", "-q", "-b", "main"); git("commit", "-q", "--allow-empty", "-m", "init")
        (r / "package.json").write_text('{"vite": "8"}\n'); (r / "yarn.lock").write_text("x\n" * 5000)
        self.assertEqual(fc.fc_gate.branch_budget(r, "main", allowed=["package.json", "yarn.lock"]), (1, [], []))


class PrText(unittest.TestCase):
    """A fake gh keeps one PR's title and body in a file; write_pr_text must only replace text the CLI itself wrote."""
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp()).resolve()
        (self.dir / "gh").write_text('''#!/usr/bin/env python3
import json, sys
a, f = sys.argv[1:], "pr.json"
try: pr = json.load(open(f))
except FileNotFoundError: pr = None
if a[:2] == ["pr", "view"]: sys.exit(1) if pr is None else print(json.dumps(pr))
if a[:2] == ["pr", "edit"]: json.dump({"title": a[a.index("--title") + 1], "body": a[a.index("--body") + 1]}, open(f, "w"))
''')
        (self.dir / "gh").chmod(0o755)
        self.env = mock.patch.dict(os.environ, {"PATH": f"{self.dir}:{os.environ['PATH']}"}); self.env.start(); self.addCleanup(self.env.stop)

    def pr(self):
        return json.loads((self.dir / "pr.json").read_text())

    def sync(self, title, body):
        before = fc.fc_stack.gh_pr_text(self.dir, "b")
        return fc.fc_stack.write_pr_text(self.dir, self.dir, "b", before, title, body)

    def test_text_is_written_on_a_new_pr_and_on_one_the_cli_wrote_but_never_over_an_edit(self):
        self.assertTrue(self.sync("t1", "b1"))
        self.assertTrue(self.sync("t2", "b2\n(231 lines)"))  # still the CLI's own text: refreshed
        self.assertEqual(self.pr(), {"title": "t2", "body": "b2\n(231 lines)"})
        (self.dir / "pr.json").write_text(json.dumps({"title": "t2", "body": "What\nWhy\nChecks"}))  # a person rewrote the body
        self.assertFalse(self.sync("t3", "b3"))
        self.assertEqual(self.pr(), {"title": "t2", "body": "What\nWhy\nChecks"})

    def test_a_pr_from_before_the_record_existed_keeps_its_text(self):
        (self.dir / "pr.json").write_text(json.dumps({"title": "hand", "body": "written"}))
        self.assertFalse(self.sync("t", "b"))
        self.assertEqual(self.pr(), {"title": "hand", "body": "written"})


FAKE_GH_STACK = """#!/usr/bin/env python3
# gh stack's local side, no login or network: init records the stack in the repo's git dir, view shows it from one of its branches
import json, subprocess, sys
from pathlib import Path
git = lambda *a: subprocess.run(["git", *a], capture_output=True, text=True).stdout.strip()
a, f = sys.argv[1:], Path(git("rev-parse", "--path-format=absolute", "--git-common-dir")) / "fake-gh-stack.json"
s = json.loads(f.read_text()) if f.exists() else None
open(f.with_name("fake-gh-calls"), "a").write(" ".join(a) + "\\n")
if a[:2] == ["stack", "init"]:
    f.write_text(json.dumps({"trunk": a[a.index("--base") + 1], "branches": [{"name": b} for b in a[4:]]}))
elif a[:2] == ["stack", "view"] and s and git("branch", "--show-current") in [b["name"] for b in s["branches"]]:
    print(json.dumps(s))
elif a[:2] == ["stack", "unstack"]:
    f.unlink(missing_ok=True)
else:
    sys.exit(1)
"""


class Layers(unittest.TestCase):
    """A project branch with groundwork and every task's test on it, and task branches above it: the layers regroup all of it."""
    def setUp(self):
        bin_ = Path(tempfile.mkdtemp()).resolve()
        (bin_ / "gh").write_text(FAKE_GH_STACK); (bin_ / "gh").chmod(0o755)
        self.env = mock.patch.dict(os.environ, {**ENV, "PATH": f"{bin_}:{os.environ['PATH']}"}); self.env.start(); self.addCleanup(self.env.stop)
        self.repo = Path(tempfile.mkdtemp()).resolve()
        self.git("init", "-q", "-b", "main")
        self.git("remote", "add", "origin", "https://github.com/o/r.git")
        self.write("README.md", "hi\n"); self.commit("init")
        self.git("checkout", "-q", "-b", "compose/p")
        self.proj = self.repo / ".compose" / "p"
        (self.proj / "results").mkdir(parents=True)
        (self.repo / ".git" / "info" / "exclude").write_text("/.compose/\n")
        self.write("lock.txt", ""); self.write("bun.lock", "x\n" * 4000); self.write("setup.txt", "s\n" * 20); self.commit("groundwork one")
        self.write("stub.txt", "s\n" * 20); self.commit("groundwork two")
        tasks = [{"id": t, "protected": [f"t{t}.test"], "files": [f"{t}.src"], "after": "", "test": f"make {t}", "title": f"Build {t}", "linear": f"ENG-{t}", "body": f"## Goal\nBuild {t}.\n"}
                 for t in ("001", "002", "003")]
        (self.proj / "results" / "tasks.json").write_text(json.dumps({"feature": {}, "tasks": tasks}))
        for t in ("001", "002", "003"):
            (self.proj / "results" / f"{t}.json").write_text(json.dumps({"status": "passed"}))  # done: a submit pushes their layers
        for t in ("001", "002", "003"):
            self.write(f"t{t}.test", "t\n" * 5); self.commit(f"test {t}")
        self.sizes = {"001": 100, "002": 120, "003": 150}
        for t, base in (("001", "compose/p"), ("002", "compose/p"), ("003", "compose/p")):
            self.git("checkout", "-q", "-b", f"compose/p-{t}", base)
            self.write(f"{t}.src", "c\n" * self.sizes[t]); self.commit(f"Build {t}")
            self.git("checkout", "-q", "compose/p")

    def git(self, *a):
        return subprocess.run(["git", *a], cwd=self.repo, check=True, capture_output=True, text=True).stdout.strip()

    def write(self, name, text):
        (self.repo / name).write_text(text)

    def commit(self, msg):
        self.git("add", "-A"); self.git("commit", "-qm", msg)

    def stack(self, **cfg):
        (self.proj / "verify.json").write_text(json.dumps({"review_base": "main", **cfg}))
        out = []
        with mock.patch.object(fc.fc_core, "say", out.append):
            self.assertTrue(fc.fc_stack.register_stack(self.repo, self.proj, "compose/p"))
        return out

    def changed(self, branch, below):
        return set(self.git("diff", "--name-only", below, branch).splitlines())

    def layers(self):
        return self.git("branch", "--list", "compose/p-layer-*", "--format=%(refname:short)").split()

    def test_groundwork_is_its_own_layer_and_each_test_lands_with_its_task(self):
        out = self.stack()  # default budget 300: tasks with their tests are 105, 125 and 155 lines
        self.assertEqual(self.layers(), ["compose/p-layer-01", "compose/p-layer-02", "compose/p-layer-03"])
        self.assertEqual(self.changed("compose/p-layer-01", "main"), {"lock.txt", "bun.lock", "setup.txt", "stub.txt"})
        self.assertEqual(self.changed("compose/p-layer-02", "compose/p-layer-01"), {"t001.test", "001.src", "t002.test", "002.src"})
        self.assertEqual(self.changed("compose/p-layer-03", "compose/p-layer-02"), {"t003.test", "003.src"})
        self.assertEqual(self.git("diff", "compose/p-layer-03", "compose/p-003"), "")  # the layers add up to the project's tree
        notes = [l for l in out if l.startswith("layer ")]
        self.assertIn("groundwork x2: 40 lines; generated, not counted: bun.lock (4000 lines)", notes[0])
        self.assertIn("task 001, 002: 230 lines", notes[1])

    def test_a_review_base_that_names_no_branch_stacks_on_the_default_branch(self):
        """A project made before init recorded the branch it started from holds "main" even where the trunk is master: the
        stack sits on the default branch, never on the project branch."""
        self.stack(review_base="master")  # this repo's trunk is main: the mirror of "main" in a master repo
        self.assertEqual(json.loads((self.repo / ".git" / "fake-gh-stack.json").read_text())["trunk"], "main")
        self.assertEqual(self.changed("compose/p-layer-01", "main"), {"lock.txt", "bun.lock", "setup.txt", "stub.txt"})

    def test_test_commits_on_one_file_keep_the_trunks_order_whoever_owns_them(self):
        """Two tasks protect one test file. A commit on it alone would go to the first of them, but it was written on top of a
        commit the second task owns: it follows that commit into the second task's unit, so the layers replay the trunk's order
        on every file and add up instead of conflicting."""
        tasks = [{"id": "001", "protected": ["t001.test", "shared.test"], "files": ["001.src"], "after": ""},
                 {"id": "002", "protected": ["t002.test", "shared.test"], "files": ["002.src"], "after": ""},
                 {"id": "003", "protected": ["t003.test"], "files": ["003.src"], "after": ""}]
        (self.proj / "results" / "tasks.json").write_text(json.dumps({"feature": {}, "tasks": tasks}))
        self.write("shared.test", "a\n" * 5); self.write("t002.test", "t\n" * 6); self.commit("test 002, with the shared file")  # 002's: two of its files
        self.write("shared.test", "a\n" * 5 + "b\n" * 5); self.commit("more shared tests")  # on 001's file too, written on top of 002's commit
        out = self.stack()
        self.assertEqual([l for l in out if "STOP" in l], [])
        self.assertEqual(self.layers(), ["compose/p-layer-01", "compose/p-layer-02", "compose/p-layer-03"])
        self.assertEqual(self.changed("compose/p-layer-02", "compose/p-layer-01"), {"t001.test", "001.src", "t002.test", "002.src", "shared.test"})
        self.assertEqual(self.git("show", "compose/p-layer-02:shared.test"), "a\n" * 5 + "b\n" * 4 + "b")
        self.assertEqual(self.git("diff", "compose/p-layer-03", "compose/p-003"), "")

    def test_groundwork_written_after_a_tasks_test_gets_its_own_layer_above_that_task(self):
        """A commit no task owns, on a file a task's test commit touched before it, cannot replay in the bottom groundwork: it is a
        groundwork layer of its own right above that task, never inside the task's layer. A later commit on a file it touched goes
        to the first task above it that protects the file, not into the task below."""
        tasks = [{"id": "001", "protected": ["t001.test", "shared.test"], "files": ["001.src"], "after": ""},
                 {"id": "002", "protected": ["t002.test"], "files": ["002.src"], "after": ""},
                 {"id": "003", "protected": ["t003.test", "shared.test"], "files": ["003.src"], "after": ""}]
        (self.proj / "results" / "tasks.json").write_text(json.dumps({"feature": {}, "tasks": tasks}))
        self.write("t002.test", "g\n" + "t\n" * 5); self.write("shared.test", "g\n"); self.commit("guard every test")  # no task owns both
        self.write("shared.test", "g\n" + "a\n" * 5); self.commit("tests for 003")  # protected by 001 and 003, written after the guard
        out = self.stack()
        self.assertEqual([l for l in out if "STOP" in l], [])
        self.assertEqual(self.layers(), ["compose/p-layer-01", "compose/p-layer-02", "compose/p-layer-03", "compose/p-layer-04"])
        self.assertEqual(self.changed("compose/p-layer-02", "compose/p-layer-01"), {"t001.test", "001.src", "t002.test", "002.src"})
        self.assertEqual(self.changed("compose/p-layer-03", "compose/p-layer-02"), {"t002.test", "shared.test"})
        self.assertEqual(self.changed("compose/p-layer-04", "compose/p-layer-03"), {"t003.test", "003.src", "shared.test"})
        self.assertIn("layer-03  groundwork x1: 2 lines", [l for l in out if l.startswith("layer ")][2])
        self.assertEqual(self.git("diff", "compose/p-layer-04", "compose/p-003"), "")

    def test_a_test_commit_goes_to_the_task_its_test_writer_wrote_it_for(self):
        """Tasks 001 and 003 both protect one test file. 003's test writer, teammate tests-003, commits its test on top of 001's
        within the span of its reports: it lands in 003's layer, not in the first layer whose task protects the file."""
        tasks = [{"id": "001", "protected": ["t001.test", "shared.test"], "files": ["001.src"], "after": ""},
                 {"id": "002", "protected": ["t002.test"], "files": ["002.src"], "after": ""},
                 {"id": "003", "protected": ["t003.test", "shared.test"], "files": ["003.src"], "after": ""}]
        (self.proj / "results" / "tasks.json").write_text(json.dumps({"feature": {}, "tasks": tasks}))
        self.write("shared.test", "a\n" * 5); self.commit("tests for 001")  # no writer's span holds it: the first task's
        crew = self.proj / "results" / "crew"; crew.mkdir()
        (crew / f"{fc.fc_herdr.agent_name('p', 'tests-003')}.status").write_text("".join(json.dumps({"at": at, "state": "working", "message": m}) + "\n"
            for at, m in (("2026-01-01 10:00:00", "started"), ("2026-01-01 10:05:00", "test ready: 1234567"))))
        self.write("shared.test", "a\n" * 5 + "b\n" * 5); self.git("add", "-A"); self.git("commit", "-qm", "tests for 003", "--date", "2026-01-01T10:02:00")
        out = self.stack()
        self.assertEqual([l for l in out if "STOP" in l], [])
        self.assertEqual(self.layers(), ["compose/p-layer-01", "compose/p-layer-02", "compose/p-layer-03"])
        self.assertEqual(self.git("show", "compose/p-layer-02:shared.test"), "a\n" * 4 + "a")
        self.assertEqual(self.changed("compose/p-layer-03", "compose/p-layer-02"), {"t003.test", "003.src", "shared.test"})
        self.assertEqual(self.git("diff", "compose/p-layer-03", "compose/p-003"), "")

    def test_a_test_commit_skips_an_earlier_one_on_its_file_it_does_not_build_on(self):
        """Task 004 has not passed: the test its writer made rides in the top layer. 001's test comes after it on the same file, in
        another part of it: it still lands in 001's layer. One that edits 004's test follows that test into the top layer."""
        tasks = [{"id": "001", "protected": ["t001.test", "shared.test"], "files": ["001.src"], "after": ""},
                 {"id": "002", "protected": ["t002.test"], "files": ["002.src"], "after": ""},
                 {"id": "003", "protected": ["t003.test"], "files": ["003.src"], "after": ""},
                 {"id": "004", "protected": ["t004.test", "shared.test"], "files": ["004.src"], "after": ""}]
        (self.proj / "results" / "tasks.json").write_text(json.dumps({"feature": {}, "tasks": tasks}))
        part = lambda a, b: f"class A\n{a}" + "-\n" * 8 + f"class B\n{b}"
        self.write("shared.test", part("", "")); self.write("stub.txt", "s\n" * 21); self.commit("a part of the test file for each task")
        crew = self.proj / "results" / "crew"; crew.mkdir()
        (crew / f"{fc.fc_herdr.agent_name('p', 'tests-004')}.status").write_text("".join(json.dumps({"at": at, "state": "working", "message": m}) + "\n"
            for at, m in (("2026-01-01 10:00:00", "started"), ("2026-01-01 10:05:00", "test ready: 1234567"))))
        self.write("shared.test", part("", "b\n" * 5)); self.git("add", "-A"); self.git("commit", "-qm", "tests for 004", "--date", "2026-01-01T10:02:00")
        self.write("shared.test", part("a\n" * 5, "b\n" * 5)); self.commit("tests for 001")
        self.write("shared.test", part("a\n" * 5, "b\n" * 4 + "c\n")); self.commit("fix a test of 004")  # 001 owns it too
        out = self.stack()
        self.assertEqual([l for l in out if "STOP" in l], [])
        self.assertEqual(self.layers(), ["compose/p-layer-01", "compose/p-layer-02", "compose/p-layer-03"])
        self.assertEqual(self.git("show", "compose/p-layer-02:shared.test") + "\n", part("a\n" * 5, ""))
        self.assertEqual(self.changed("compose/p-layer-03", "compose/p-layer-02"), {"t003.test", "003.src", "shared.test"})
        self.assertEqual(self.git("diff", "compose/p-layer-03", "compose/p-003"), "")

    def test_a_redone_test_writer_owns_only_the_commits_of_its_own_runs_not_the_gap_between_them(self):
        """Tests-003 ran at 10:10 and again at 12:00. Tests-001, redone at 11:00 in between, made the commit at 11:02 on their shared
        file: it lands in 001's layer, not in 003's, whose first and last report would otherwise span it."""
        tasks = [{"id": "001", "protected": ["t001.test", "shared.test"], "files": ["001.src"], "after": ""},
                 {"id": "002", "protected": ["t002.test"], "files": ["002.src"], "after": ""},
                 {"id": "003", "protected": ["t003.test", "shared.test"], "files": ["003.src"], "after": ""}]
        (self.proj / "results" / "tasks.json").write_text(json.dumps({"feature": {}, "tasks": tasks}))
        crew = self.proj / "results" / "crew"; crew.mkdir()
        for t, runs in (("001", (("10:00:00", "started"), ("10:05:00", "test ready"), ("10:06:00", "done"), ("11:00:00", "started"), ("11:05:00", "done"))),
                        ("003", (("10:10:00", "started"), ("10:15:00", "done"), ("12:00:00", "started"), ("12:05:00", "done")))):
            (crew / f"{fc.fc_herdr.agent_name('p', f'tests-{t}')}.status").write_text("".join(
                json.dumps({"at": f"2026-01-01 {at}", "state": "done" if m == "done" else "working", "message": m}) + "\n" for at, m in runs))
        part = lambda a, b: f"class A\n{a}" + "-\n" * 8 + f"class B\n{b}"
        for at, a, b in (("10:02:00", "a\n" * 5, ""), ("10:12:00", "a\n" * 5, "b\n" * 5), ("11:02:00", "a\n" * 4 + "x\n", "b\n" * 5)):
            self.write("shared.test", part(a, b)); self.git("add", "-A"); self.git("commit", "-qm", f"tests at {at}", "--date", f"2026-01-01T{at}")
        out = self.stack()
        self.assertEqual([l for l in out if "STOP" in l], [])
        self.assertEqual(self.git("show", "compose/p-layer-02:shared.test") + "\n", part("a\n" * 4 + "x\n", ""))
        self.assertEqual(self.changed("compose/p-layer-03", "compose/p-layer-02"), {"t003.test", "003.src", "shared.test"})
        self.assertEqual(self.git("diff", "compose/p-layer-03", "compose/p-003"), "")

    def test_a_task_over_the_budget_is_never_split(self):
        out = self.stack(review_layer_lines=130)
        self.assertEqual(len(self.layers()), 4)
        self.assertEqual(self.changed("compose/p-layer-04", "compose/p-layer-03"), {"t003.test", "003.src"})
        self.assertIn("task 003: 155 lines; over the 130-line budget", out[-1])

    def test_a_submitted_stack_keeps_each_task_in_its_layer_when_sizes_change(self):
        self.stack(review_layer_lines=300)
        fc.fc_layers.record_layers(self.proj, [{"branch": b, "tasks": t} for b, t in (("compose/p-layer-01", ["groundwork"]), ("compose/p-layer-02", ["001", "002"]), ("compose/p-layer-03", ["003"]))])
        self.git("checkout", "-q", "compose/p-003")
        self.write("003.src", "c\n"); self.commit("shrink 003")  # 003 now fits with 001 and 002, so a regroup would merge layers 02 and 03
        self.git("checkout", "-q", "compose/p")
        self.stack(review_layer_lines=300)
        self.assertEqual(self.layers(), ["compose/p-layer-01", "compose/p-layer-02", "compose/p-layer-03"])
        self.assertEqual(self.changed("compose/p-layer-03", "compose/p-layer-02"), {"t003.test", "003.src"})

    def test_a_task_new_since_the_submit_gets_a_layer_above(self):
        self.stack()
        fc.fc_layers.record_layers(self.proj, [{"branch": b, "tasks": t} for b, t in (("compose/p-layer-01", ["groundwork"]), ("compose/p-layer-02", ["001"]))])
        self.stack()
        self.assertEqual(self.layers(), ["compose/p-layer-01", "compose/p-layer-02", "compose/p-layer-03"])
        self.assertEqual(self.changed("compose/p-layer-02", "compose/p-layer-01"), {"t001.test", "001.src"})
        self.assertEqual(self.changed("compose/p-layer-03", "compose/p-layer-02"), {"t002.test", "002.src", "t003.test", "003.src"})

    def test_a_rebuild_from_unchanged_commits_keeps_the_hashes(self):
        self.stack()
        before = self.git("rev-parse", "compose/p-layer-01", "compose/p-layer-02")
        self.stack()
        self.assertEqual(self.git("rev-parse", "compose/p-layer-01", "compose/p-layer-02"), before)

    def test_the_gh_stack_is_the_layers_on_the_real_base(self):
        self.stack()
        wt = fc.fc_worktree.stack_worktree(self.repo, self.proj, "compose/p")
        subprocess.run(["git", "checkout", "-q", "compose/p-layer-02"], cwd=wt, check=True)
        data = json.loads(subprocess.run(["gh", "stack", "view", "--json"], cwd=wt, capture_output=True, text=True).stdout)
        self.assertEqual(data["trunk"], "main")
        self.assertEqual([b["name"] for b in data["branches"]], self.layers())

    def stop(self, breaks):
        """Run `compose stack` after a first good build and `breaks`; return its STOP lines, having checked that it exits non-zero and
        changes no layer branch, recorded layer or gh stack."""
        self.stack()
        breaks()
        fc.fc_layers.record_layers(self.proj, [{"branch": b, "tasks": [b]} for b in self.layers()])
        refs = lambda: self.git("for-each-ref", "--format=%(refname) %(objectname)", "refs/heads/compose/p-layer-*")
        before = (refs(), (self.proj / "layers.json").read_text(), (self.repo / ".git" / "fake-gh-stack.json").read_text())
        calls = lambda: [c for c in (self.repo / ".git" / "fake-gh-calls").read_text().splitlines() if not c.startswith("pr view")]  # reading a PR's state changes nothing
        out, seen = [], calls()
        with mock.patch.object(fc.fc_core, "say", out.append), self.assertRaises(SystemExit) as e:
            fc.fc_ship.cmd_stack(argparse.Namespace(repo=str(self.repo), project="p", trunk="compose/p", submit=False, update=False))
        self.assertTrue(e.exception.code)
        self.assertEqual((refs(), (self.proj / "layers.json").read_text(), (self.repo / ".git" / "fake-gh-stack.json").read_text()), before)
        self.assertEqual(calls(), seen)
        return [l for l in out if "STOP" in l]

    def test_a_project_branch_behind_its_base_stops_the_stack_with_layers_and_gh_stack_untouched(self):
        def main_moves_on():
            self.git("checkout", "-q", "main"); self.write("setup.txt", "main\n"); self.commit("main moves on"); self.git("checkout", "-q", "compose/p")
        stops = self.stop(main_moves_on)
        main = self.git("rev-parse", "--short", "main")
        self.assertEqual(len(stops), 1)
        self.assertIn(f"compose/p conflicts with main {main} in setup.txt; the layers and the stack are left as they were. "
                      "Rebase compose/p onto main, then re-run", stops[0])

    def test_a_checkout_on_a_task_branch_stops_the_stack_and_keeps_every_layer(self):
        for at in ("compose/p-003", "compose/p-002"):  # all task branches are in HEAD, or only the ones below
            with self.subTest(at):
                stops = self.stop(lambda: self.git("checkout", "-q", at))
                self.assertEqual(len(stops), 1)
                self.assertIn(f"HEAD is on {at}, one of the project's own branches, not on compose/p", stops[0])
                self.git("checkout", "-q", "compose/p")

    def test_a_detached_head_that_holds_task_branches_stops_the_stack_too(self):
        stops = self.stop(lambda: self.git("checkout", "-q", "--detach", "compose/p-003"))
        self.assertEqual(len(stops), 1)
        self.assertIn("HEAD holds the unmerged task branches compose/p-001, compose/p-002, compose/p-003, which would be left out of the stack", stops[0])

    def test_a_chain_rebase_that_stops_stops_the_stack_verify_and_top_before_they_act_on_the_layers_below_it(self):
        def task_003_conflicts_with_002():
            self.git("checkout", "-q", "-B", "compose/p-003", "compose/p")
            self.write("002.src", "other\n"); self.write("003.src", "c\n"); self.commit("task 003 redone"); self.git("checkout", "-q", "compose/p")
        stops = self.stop(task_003_conflicts_with_002)
        why = "compose/p-003 conflicts when rebased onto compose/p-002 in 002.src; the layers below it are kept. Resolve by hand: git checkout compose/p-003 && git rebase --onto compose/p-002 "
        self.assertEqual(len(stops), 1); self.assertIn(why, stops[0])
        a = argparse.Namespace(repo=str(self.repo), project="p", fix=0, skip_review=True, skip_e2e=True, detach=False)
        said = {}
        for cmd in (fc.fc_verify.cmd_verify, fc.fc_status.cmd_top):
            out = said[cmd.__name__] = []
            with self.subTest(cmd.__name__):
                with mock.patch.object(fc.fc_core, "say", out.append), \
                        mock.patch.object(fc.fc_verify, "run_stages", side_effect=AssertionError("a stage ran")), self.assertRaises(SystemExit) as e:
                    cmd(a)
                self.assertEqual(e.exception.code, 1)
        self.assertTrue(said["cmd_verify"][-1].startswith("verify FAIL  nothing verified or recorded: " + why), said["cmd_verify"])
        self.assertFalse((self.proj / "results" / "verify.json").exists())

    def hold_stack_top(self, kind="verify"):
        """A verify of project p alive in another process, as `compose verify` records it, and the worktree it stands in at the stack top."""
        proc = subprocess.Popen(["sleep", "60"]); self.addCleanup(proc.wait); self.addCleanup(proc.kill)
        live = fc.fc_update.live_dir(); live.mkdir(parents=True, exist_ok=True)
        (live / f"{proc.pid}.json").write_text(json.dumps({"pid": proc.pid, "kind": kind, "project": "p", "repo": str(self.repo), "since": "21:01"}))
        return proc

    def test_stack_top_commands_refuse_while_a_verify_holds_the_stack_top_and_leave_it_where_it_is(self):
        self.stack()
        wt, _, _ = fc.fc_verify.verify_root(self.repo, self.proj, {})
        top = lambda: self.git("-C", str(wt), "branch", "--show-current")
        at = top(); self.assertEqual(at, "compose/p-003")
        proc = self.hold_stack_top()
        ns = lambda **kw: argparse.Namespace(repo=str(self.repo), project="p", trunk="compose/p", **kw)
        for name, cmd, args in (("stack", fc.fc_ship.cmd_stack, ns(submit=False, update=False)), ("stack --submit", fc.fc_ship.cmd_stack, ns(submit=True, update=False)),
                                ("top", fc.fc_status.cmd_top, ns(detach=False)), ("top --detach", fc.fc_status.cmd_top, ns(detach=True)),
                                ("reword", fc.fc_ship.cmd_reword, ns(set=["abc=Add it"], as_is=False))):
            with self.subTest(name), self.assertRaises(SystemExit) as e:
                cmd(args)
            self.assertIn(f"verify is running on p (pid {proc.pid}, since 21:01)", str(e.exception))
            self.assertEqual(top(), at)
        proc.kill(); proc.wait()  # the verify ended: the stack runs again
        self.stack()

    def test_a_verify_whose_checkout_moved_off_its_branch_during_a_stage_is_void_and_records_nothing(self):
        self.stack()
        wt = fc.fc_worktree.stack_worktree(self.repo, self.proj, "compose/p")
        def stack_moves_it(*a, **k):
            self.git("-C", str(wt), "checkout", "-q", "--detach", "compose/p")
            return True, {"checks": []}, ""
        a = argparse.Namespace(repo=str(self.repo), project="p", fix=0, skip_review=True, skip_e2e=True, detach=False)
        out = []
        with mock.patch.object(fc.fc_core, "say", out.append), mock.patch.object(fc.fc_verify, "run_stages", side_effect=stack_moves_it), self.assertRaises(SystemExit) as e:
            fc.fc_verify.cmd_verify(a)
        self.assertEqual(e.exception.code, 1)
        self.assertTrue(any(l.startswith("verify VOID  nothing verified or recorded: ") and "compose/p-003" in l and "detached" in l for l in out), out)
        self.assertFalse((self.proj / "results" / "verify.json").exists())

    def test_layers_that_do_not_add_up_to_the_chain_stop_the_stack_with_layers_and_gh_stack_untouched(self):
        real, broken = fc.fc_layers.review_units, mock.patch.object(fc.fc_layers, "review_units", lambda *a: real(*a)[:-1])
        stops = self.stop(broken.start)  # the top task's unit goes missing
        broken.stop()
        self.assertEqual(stops, ["stack  STOP  the layers differ from compose/p-003 in 003.src, t003.test; the layers and the stack are left as they were"])

    def submit(self):
        """Run `compose stack --submit`; return its lines and exit code (0 when it returned)."""
        out = []
        with mock.patch.object(fc.fc_core, "say", out.append):
            try:
                fc.fc_ship.cmd_stack(argparse.Namespace(repo=str(self.repo), project="p", trunk="compose/p", submit=True, update=False))
            except SystemExit as e:
                return out, e.code
        return out, 0

    def test_a_base_ahead_of_its_upstream_warns_and_a_submit_stops_with_nothing_changed(self):
        self.git("update-ref", "refs/remotes/origin/main", "main"); self.git("branch", "-q", "--set-upstream-to=origin/main", "main")
        self.git("checkout", "-q", "main")
        for n in ("1", "2"):
            self.write(f"unpushed{n}.txt", "u\n"); self.commit(f"unpushed {n}")
        self.git("checkout", "-q", "compose/p")
        self.assertIn("stack  WARN  main is 2 commits ahead of origin/main, so the PRs would carry them; --submit stops until main is pushed", self.stack())
        refs = lambda: self.git("for-each-ref", "--format=%(refname) %(objectname)", "refs/heads/compose/p*")
        before = (refs(), (self.repo / ".git" / "fake-gh-stack.json").read_text(), (self.repo / ".git" / "fake-gh-calls").read_text())
        out, code = self.submit()
        self.assertEqual(code, 1)
        self.assertEqual(out, ["stack  STOP  main is 2 commits ahead of origin/main, so the PRs would carry them; nothing was built or pushed. "
                               "Push main, or wait until origin/main has them, then re-run"])
        self.assertEqual((refs(), (self.repo / ".git" / "fake-gh-stack.json").read_text(), (self.repo / ".git" / "fake-gh-calls").read_text()), before)

    def test_a_base_even_with_or_behind_its_upstream_or_without_one_submits_without_a_word(self):
        for upstream in ("none", "even", "behind"):
            if upstream != "none":
                self.git("update-ref", "refs/remotes/origin/main", "main"); self.git("branch", "-q", "--set-upstream-to=origin/main", "main")
            if upstream == "behind":
                self.git("checkout", "-q", "-b", "elsewhere", "main"); self.write("theirs.txt", "t\n"); self.commit("pushed by someone else")
                self.git("update-ref", "refs/remotes/origin/main", "elsewhere"); self.git("checkout", "-q", "compose/p")
            (self.proj / "verify.json").write_text(json.dumps({"review_base": "main"}))
            calls = self.repo / ".git" / "fake-gh-calls"
            seen = len(calls.read_text().splitlines()) if calls.exists() else 0
            out, code = self.submit()
            self.assertEqual(code, 0, upstream)
            self.assertFalse([l for l in out if "WARN" in l or "STOP" in l], upstream)
            self.assertIn("stack submit --auto", calls.read_text().splitlines()[seen:], upstream)

    def test_stack_without_submit_prints_each_layers_pr_title_and_body_and_calls_no_gh_pr(self):
        (self.proj / "verify.json").write_text(json.dumps({"review_base": "main"}))
        cache = json.loads((self.proj / "results" / "tasks.json").read_text())
        (self.proj / "results" / "tasks.json").write_text(json.dumps({**cache, "feature": {"title": "Build it", "description": "Fixes o/r#9."}}))
        out = []
        with mock.patch.object(fc.fc_core, "say", out.append):
            fc.fc_ship.cmd_stack(argparse.Namespace(repo=str(self.repo), project="p", trunk="compose/p", submit=False, update=False))
        prs = [l for l in out if l.startswith("pr ")]
        self.assertEqual([l.split()[1] for l in prs], self.layers())
        for i, l in enumerate(prs, 1):
            self.assertIn(f"({i}/3)", l.splitlines()[0])
            self.assertIn("## What changed", l)
            self.assertNotRegex(l, r" lines|attempt")  # no size line or attempt count reaches a reviewer
        self.assertIn("## What changed\n    - Build 001\n    - Build 002\n\n", prs[1])  # one line per task, its test commit folded in
        self.assertIn("- Part of o/r#9", prs[1])  # as submit writes it: the issue is fixed by the layer with its last task
        self.assertIn("- Fixes o/r#9", prs[2])
        calls =(self.repo / ".git" / "fake-gh-calls").read_text().splitlines()
        self.assertFalse([c for c in calls if not c.startswith("stack ")])
        self.assertFalse((self.proj / "pr_text.json").exists())

    def preview(self, **cfg):
        """`compose stack`'s pr lines without --submit: ({branch: its pr line and body}, the other pr lines)."""
        (self.proj / "verify.json").write_text(json.dumps({"review_base": "main", **cfg}))
        out = []
        with mock.patch.object(fc.fc_core, "say", out.append):
            fc.fc_stack.register_stack(self.repo, self.proj, "compose/p", preview=True)
        prs = [l for l in out if l.startswith("pr ")]
        return {l.split()[1]: l for l in prs if l.split()[1] in self.layers()}, [l for l in prs if l.split()[1] not in self.layers()]

    def pr_file(self, name, text):
        (self.proj / "pr").mkdir(exist_ok=True)
        (self.proj / "pr" / f"{name}.md").write_text(text)

    WRITTEN = ("# Keep the toggle's state across reloads\n\n## Why\nThe toggle forgot its state on every reload.\nThis stores it.\n\n"
               "## What changed\n- Store the toggle's state\n- Read it back on load\n")

    def test_a_layers_written_pr_text_replaces_its_title_why_and_what_changed_and_compose_keeps_the_facts(self):
        cache = json.loads((self.proj / "results" / "tasks.json").read_text())
        (self.proj / "results" / "tasks.json").write_text(json.dumps({**cache, "feature": {"title": "Build it", "description": "Fixes o/r#9."}}))
        self.pr_file("001-002", self.WRITTEN)
        self.pr_file("groundwork", "# Prepare the build\n\n## Why\nIt needs stubs.\n\n## What changed\n- Add stubs\n\n## Notes\nmore\n")
        prs, rest = self.preview()
        self.assertEqual(rest, [])
        self.assertEqual(prs["compose/p-layer-02"],
                         "pr     compose/p-layer-02  Keep the toggle's state across reloads (2/3)  [written: .compose/p/pr/001-002.md]\n"
                         "    ## Why\n    The toggle forgot its state on every reload.\n    This stores it.\n    - Part of o/r#9\n\n"
                         "    ## What changed\n    - Store the toggle's state\n    - Read it back on load\n\n"
                         "    ## How it was tested\n    - `make 001`\n    - `make 002`\n\n    ## Tickets\n    - ENG-001\n    - ENG-002")
        self.assertIn("Build 003 (3/3)  [generated: write .compose/p/pr/003.md]\n", prs["compose/p-layer-03"])
        self.assertIn("- Fixes o/r#9", prs["compose/p-layer-03"])
        self.assertIn("  [generated: .compose/p/pr/groundwork.md refused: after the title it must be `## Why` then `## What changed`, nothing else]\n",
                      prs["compose/p-layer-01"])
        self.assertNotIn("Prepare the build", prs["compose/p-layer-01"])

    def test_a_pr_text_file_follows_its_tasks_to_a_new_layer_and_one_whose_tasks_were_regrouped_is_never_applied(self):
        self.pr_file("003", self.WRITTEN)
        self.pr_file("001-002", self.WRITTEN.replace("Keep the toggle's", "Show the panel's"))
        prs, rest = self.preview(review_layer_lines=1)  # two groundwork layers, then one layer per task
        self.assertEqual(list(prs), [f"compose/p-layer-0{i}" for i in range(1, 6)])
        self.assertIn("Keep the toggle's state across reloads (5/5)  [written: .compose/p/pr/003.md]", prs["compose/p-layer-05"])
        self.assertIn("[generated: write .compose/p/pr/groundwork-2.md]", prs["compose/p-layer-02"])
        self.assertFalse([l for l in prs.values() if "Show the panel's" in l])
        self.assertEqual(rest, ["pr     .compose/p/pr/001-002.md matches no layer, so no PR uses it; the layers' files are "
                                "groundwork.md, groundwork-2.md, 001.md, 002.md, 003.md"])

    def test_pr_text_is_a_title_why_and_bullets_and_anything_else_is_refused_with_the_reason(self):
        f = Path(tempfile.mkdtemp()) / "001.md"
        self.assertIsNone(fc.fc_stack.pr_text(f, 72))
        f.write_text(self.WRITTEN.replace("\n\n## Why", "\n\n\n## Why\n").replace("on load\n", "on load\n\n\n"))
        self.assertEqual(fc.fc_stack.pr_text(f, 72), ("Keep the toggle's state across reloads",
                         ["The toggle forgot its state on every reload.", "This stores it."], ["- Store the toggle's state", "- Read it back on load"]))
        for text, why in [("Keep it\n## Why\nx\n## What changed\n- y", "line 1 must be `# <title>`"),
                          ("# JS-7: Keep it\n## Why\nx\n## What changed\n- y", "ticket key or (i/n)"),
                          ("# Keep it (2/3)\n## Why\nx\n## What changed\n- y", "ticket key or (i/n)"),
                          ("# " + "x" * 73 + "\n## Why\nx\n## What changed\n- y", "the title is 73 characters, at most 72"),
                          ("# Keep it\nintro\n## Why\nx\n## What changed\n- y", "`## Why` then `## What changed`, nothing else"),
                          ("# Keep it\n## What changed\n- y\n## Why\nx", "`## Why` then `## What changed`, nothing else"),
                          ("# Keep it\n## Why\nx\n## What changed\n- y\n### More\n", "`## Why` then `## What changed`, nothing else"),
                          ("# Keep it\n## Why\n\n## What changed\n- y", "must not be empty"),
                          ("# Keep it\n## Why\nx\nFixes o/r#9\n## What changed\n- y", "compose adds the Fixes and Part of lines"),
                          ("# Keep it\n## Why\nx\n## What changed\n- y\nz", "must be a `- ` bullet")]:
            f.write_text(text)
            with self.assertRaises(ValueError) as e:
                fc.fc_stack.pr_text(f, 72)
            self.assertIn(why, str(e.exception), text)


class LayerNames(unittest.TestCase):
    """The Layers project with its task branches under the task prefix: the layers and the chain take their names from it."""
    setUp, git, write, commit, stack, changed = Layers.setUp, Layers.git, Layers.write, Layers.commit, Layers.stack, Layers.changed

    def rename(self, prefix):
        for t in ("001", "002", "003"):
            self.git("branch", "-m", f"compose/p-{t}", f"{prefix}{t}")

    def layers(self, prefix="compose/p-"):
        return self.git("branch", "--list", f"{prefix}layer-*", "--format=%(refname:short)").split()

    def test_a_new_project_cuts_its_task_branches_into_layers_named_from_its_branch(self):
        out = self.stack()
        self.assertEqual(self.layers(), ["compose/p-layer-01", "compose/p-layer-02", "compose/p-layer-03"])
        self.assertEqual(self.changed("compose/p-layer-02", "compose/p-layer-01"), {"t001.test", "001.src", "t002.test", "002.src"})
        self.assertEqual(self.changed("compose/p-layer-03", "compose/p-layer-02"), {"t003.test", "003.src"})
        self.assertEqual(self.git("diff", "compose/p-layer-03", "compose/p-003"), "")
        self.assertTrue(any(l.startswith("layer  layer-01") for l in out))
        self.assertEqual(json.loads((self.proj / "verify.json").read_text())["layer_prefix"], "compose/p-")
        before = self.git("rev-parse", *self.layers())
        self.stack()  # the layer branches share the task prefix, and are never taken for tasks
        self.assertEqual(self.git("rev-parse", *self.layers()), before)

    def test_a_task_whose_tip_holds_another_sits_above_it(self):
        self.git("checkout", "-q", "-B", "compose/p-001", "compose/p-003")
        self.write("001.src", "c\n" * 100); self.commit("task 001 on 003")
        self.git("checkout", "-q", "compose/p")
        out = self.stack()
        self.assertEqual([l for l in out if "STOP" in l], [])
        self.assertEqual(self.changed("compose/p-layer-03", "compose/p-layer-02"), {"t001.test", "001.src"})
        self.assertEqual(self.git("diff", "compose/p-layer-03", "compose/p-001"), "")

    def test_a_replaced_tip_is_dropped_from_the_layer_above_and_its_ref_deleted(self):
        self.git("checkout", "-q", "-B", "compose/p-003", "compose/p-002")
        self.write("003.src", "c\n" * 150); self.commit("task 003 on 002")
        fc.fc_worktree.replace_branch(self.repo, self.proj, "compose/p-002")
        self.git("checkout", "-q", "-b", "compose/p-002", "compose/p")
        self.write("002.src", "d\n" * 120); self.commit("task 002 again")
        self.git("checkout", "-q", "compose/p")
        out = self.stack()
        self.assertEqual([l for l in out if "STOP" in l], [])
        self.assertEqual(self.git("show", "compose/p-layer-03:002.src"), "d\n" * 119 + "d")
        self.assertEqual(self.git("diff", "compose/p-layer-03", "compose/p-003"), "")
        self.assertEqual(self.git("for-each-ref", "refs/compose/replaced/"), "")

    def test_a_legacy_project_never_pushed_takes_the_new_names_before_its_layers_are_cut(self):
        self.rename("fast/p/")
        self.git("branch", "fast/p/layer-09", "main")  # an earlier stack's layer, never pushed
        out = self.stack(branch="compose/p")
        self.assertIn("names  renamed 4 never-pushed fast/p/* branch(es) to compose/p-*", out)
        self.assertEqual(self.git("branch", "--list", "fast/*"), "")
        self.assertEqual(self.layers(), ["compose/p-layer-01", "compose/p-layer-02", "compose/p-layer-03"])
        self.assertEqual(self.git("diff", "compose/p-layer-03", "compose/p-003"), "")
        cfg = json.loads((self.proj / "verify.json").read_text())
        self.assertEqual((cfg["task_prefix"], cfg["layer_prefix"]), ("compose/p-", "compose/p-"))

    def test_a_legacy_project_with_a_pushed_branch_keeps_fast_names_unless_a_prefix_is_recorded(self):
        self.rename("fast/p/")
        self.git("update-ref", "refs/remotes/origin/fast/p/layer-01", "main")
        self.stack(branch="compose/p")
        self.assertEqual(self.layers("fast/p/"), ["fast/p/layer-01", "fast/p/layer-02", "fast/p/layer-03"])
        self.assertEqual(json.loads((self.proj / "verify.json").read_text())["layer_prefix"], "fast/p/")
        self.stack(branch="compose/p", layer_prefix="review/p-")
        self.assertEqual(self.layers("review/p-"), ["review/p-layer-01", "review/p-layer-02", "review/p-layer-03"])

    def test_a_recorded_task_prefix_names_the_layers(self):
        self.rename("feat/p-")
        self.stack(task_prefix="feat/p-")
        self.assertEqual(self.layers("feat/p-"), ["feat/p-layer-01", "feat/p-layer-02", "feat/p-layer-03"])
        self.assertEqual(self.git("diff", "feat/p-layer-03", "feat/p-003"), "")


class StackLimit(unittest.TestCase):
    """Adjacent layers fold until the stack has no more PRs than max_stack_prs: same kind first, then any; recorded layers never."""
    setUp, git, write, commit, stack = Layers.setUp, Layers.git, Layers.write, Layers.commit, Layers.stack

    def groups(self, units, cap):
        return [(b, [u["name"] for u in g], f) for b, g, f in fc.fc_layers.group_by_record(self.proj, units, 300, cap)]

    def test_twelve_one_task_layers_fold_the_lowest_pair_into_ten_the_lower_on_a_tie(self):
        us = [unit(f"{i:03d}", 400) for i in range(1, 13)]
        alone = [(None, [u["name"]], False) for u in us]
        self.assertEqual(self.groups(us, None), alone)
        self.assertEqual(self.groups(us, 12), alone)
        self.assertEqual(self.groups(us, 10), [(None, ["001", "002"], True), (None, ["003", "004"], True)] + alone[4:])
        self.assertEqual(self.groups([unit("001", 400), unit("002", 500), unit("003", 350)], 2), [(None, ["001"], False), (None, ["002", "003"], True)])

    def test_groundwork_and_a_task_fold_together_only_when_no_same_kind_pair_is_left(self):
        us = [unit("groundwork", 10), unit("001", 400), unit("002", 400), unit("groundwork", 10)]
        self.assertEqual(self.groups(us, 3), [(None, ["groundwork"], False), (None, ["001", "002"], True), (None, ["groundwork"], False)])
        self.assertEqual(self.groups(us, 2), [(None, ["groundwork", "001", "002"], True), (None, ["groundwork"], False)])

    def test_a_recorded_layer_keeps_its_tasks_and_never_folds_even_above_the_cap(self):
        (self.proj / "layers.json").write_text(json.dumps({"fast/p/layer-01": ["001"], "fast/p/layer-02": ["002"]}))
        us = [unit(f"{i:03d}", 400) for i in range(1, 5)]
        self.assertEqual(self.groups(us, 2), [("fast/p/layer-01", ["001"], False), ("fast/p/layer-02", ["002"], False), (None, ["003", "004"], True)])

    def test_a_folded_layer_over_the_budget_says_so_on_its_layer_line_and_size_line(self):
        out = [l for l in self.stack(review_layer_lines=30, max_stack_prs=3) if l.startswith("layer ")]  # natural: 20, 20, 105, 125, 155
        self.assertEqual(len(out), 3)
        self.assertRegex(out[0], r"layer-01  groundwork x2: 40 lines.*; over the 30-line budget to stay within 3 PRs")
        self.assertRegex(out[1], r"layer-02  task 001, 002: 230 lines.*; over the 30-line budget to stay within 3 PRs")
        self.assertIn("task 003: 155 lines; over the 30-line budget, a task is never split", out[2])
        self.assertNotIn("stay within", out[2])
        l = {"tasks": ["001", "002"], "lines": 400, "generated": {}, "fold_cap": 3}
        self.assertEqual(fc.fc_layers.layer_note(l, 300), "task 001, 002: 400 lines; over the 300-line budget to stay within 3 PRs")
        self.assertEqual(fc.fc_layers.layer_note({**l, "lines": 250}, 300), "task 001, 002: 250 lines")
        g = {"tasks": ["groundwork"], "lines": 400, "generated": {}}  # a groundwork unit is one commit
        self.assertEqual(fc.fc_layers.layer_note(g, 300), "groundwork x1: 400 lines; over the 300-line budget, a commit is never split")

    def test_the_cap_is_ten_unless_set_and_verify_json_beats_the_workspace_which_beats_the_top_level(self):
        for i in range(8):  # 13 layers at a 1-line budget: two groundwork commits, these eight, three tasks
            self.write(f"g{i}.txt", "g\n"); self.commit(f"groundwork g{i}")
        cfg = Path(tempfile.mkdtemp()) / "config.json"
        count = lambda **v: len([l for l in self.stack(review_layer_lines=1, **v) if l.startswith("layer ")])
        with mock.patch.object(fc.fc_config, "CONFIG_PATH", cfg):
            self.assertEqual(count(), 10)
            cfg.write_text(json.dumps({"max_stack_prs": 5}))
            self.assertEqual(count(), 5)
            cfg.write_text(json.dumps({"max_stack_prs": 5, "workspace": "w", "workspaces": {"w": {"max_stack_prs": 4}}}))
            self.assertEqual(count(), 4)
            self.assertEqual(count(max_stack_prs=3), 3)


class PrTitle(unittest.TestCase):
    """A layer's PR is titled from its commits: one commit's subject, else its first task's title or first commit's subject and N more
    tasks or commits, never past TITLE_CHARS before its (i/n)."""
    setUp, git, write, commit, stack = Layers.setUp, Layers.git, Layers.write, Layers.commit, Layers.stack
    METAS = [{"id": "001", "title": "001: Add the toggle"}, {"id": "002", "title": "Add the panel"}, {"id": "003", "title": "Add the menu"}]

    def title(self, tasks, subjects, n=2, branch="compose/p-layer-01"):
        commits = []
        for s in subjects:
            self.git("commit", "-q", "--allow-empty", "-m", s); commits.append(self.git("rev-parse", "HEAD"))
        l = {"branch": branch, "tasks": tasks, "keys": tasks, "lines": 40, "generated": {}, "commits": commits}
        with mock.patch.object(fc.fc_stack, "layer_body", return_value=""):  # the body is not this title's concern
            return fc.fc_stack.layer_pr(self.repo, self.proj, l, n, self.METAS)[0]

    def test_each_layer_records_the_commits_it_cherry_picks_oldest_first(self):
        real, built = fc.fc_layers.build_layers, []
        with mock.patch.object(fc.fc_layers, "build_layers", lambda *a, **k: built.append(real(*a, **k)) or built[-1]):
            self.stack()
        below = "main"
        for l in built[0]:
            self.assertEqual([self.git("log", "-1", "--format=%s", c) for c in l["commits"]], self.git("log", "--reverse", "--format=%s", f"{below}..{l['branch']}").splitlines())
            below = l["branch"]
        self.assertEqual(built[0][0]["commits"], self.git("rev-list", "--reverse", f"main..{built[0][0]['branch']}").split())
        self.assertEqual(len(built[0][1]["commits"]), 4)  # test 001, task 001, test 002, task 002

    def test_a_one_commit_layer_is_its_subject_and_a_groundwork_layer_its_first_subject_and_n_more(self):
        self.assertEqual(self.title(["groundwork"], ["Ignore build output"]), "Ignore build output (1/2)")
        self.assertEqual(self.title(["groundwork"] * 3, ["Ignore build output", "Pin the toolchain", "Add a lint step"]), "Ignore build output and 2 more commits (1/2)")

    def test_a_task_layer_is_its_first_tasks_title_and_n_more_counting_only_its_other_tasks(self):
        subjects = ["test 001", "toggle work", "test 002", "panel work", "menu work"]
        self.assertEqual(self.title(["001", "002", "003"], subjects, 4, "compose/p-layer-02"), "Add the toggle and 2 more tasks (2/4)")
        self.assertEqual(self.title(["001"], ["test 001", "toggle work"]), "Add the toggle (1/2)")
        self.assertEqual(self.title(["groundwork", "002", "003"], ["Ignore build output", "panel work", "menu work"]), "Add the panel and 1 more task (1/2)")

    def test_a_jira_key_on_the_project_branch_prefixes_the_title(self):
        (self.proj / "verify.json").write_text(json.dumps({"branch": "js-2888-react-beside-vue"}))
        self.assertEqual(self.title(["001", "002"], ["toggle work", "panel work"], 4, "js-2888-react-beside-vue-layer-03"), "JS-2888: Add the toggle and 1 more task (3/4)")
        self.assertEqual(self.title(["groundwork"], ["Ignore build output"]), "JS-2888: Ignore build output (1/2)")
        Layers.pr_file(self, "001-002", Layers.WRITTEN)  # a written title gets the key and the count too, within the same cap
        self.assertEqual(self.title(["001", "002"], ["toggle work", "panel work"], 4, "js-2888-react-beside-vue-layer-03"), "JS-2888: Keep the toggle's state across reloads (3/4)")
        Layers.pr_file(self, "001-002", Layers.WRITTEN.replace("reloads", "reloads " + "x" * 30))
        self.assertEqual(self.title(["001", "002"], ["toggle work", "panel work"], 4, "js-2888-react-beside-vue-layer-03"), "JS-2888: Add the toggle and 1 more task (3/4)")
        self.linear()
        self.assertEqual(self.title(["001", "002", "003"], ["toggle work", "panel work", "menu work"], 1), "JS-2888: Stacked [PRs]")

    def linear(self):
        issues = {"NEB-10": {"title": "Users flip the toggle (C2)", "parentId": "NEB-9"}, "NEB-20": {"title": "Open the menu", "parentId": "NEB-9"},
                  "NEB-1": {"parentId": "NEB-10"}, "NEB-2": {"parentId": "NEB-10"}, "NEB-3": {"parentId": "NEB-20"}}
        (self.proj / "results" / "tasks.json").write_text(json.dumps({"feature": {"id": "NEB-9", "title": "Stacked \\[PRs\\]"}, "tasks": [], "issues": issues}))
        self.METAS = [{**m, "linear": f"NEB-{i}"} for i, m in enumerate(PrTitle.METAS, 1)]

    def test_a_one_pr_stack_is_titled_by_its_feature_and_has_no_count(self):
        self.assertEqual(self.title(["001", "002"], ["toggle work", "panel work"], 1), "Add the toggle and 1 more task")  # no feature title known
        self.linear()
        self.assertEqual(self.title(["001", "002", "003"], ["test 001", "toggle work", "panel work", "menu work"], 1), "Stacked [PRs]")
        self.assertEqual(self.title(["groundwork"], ["Ignore build output"], 1), "Stacked [PRs]")

    def test_a_layer_holding_one_whole_story_is_titled_by_that_story(self):
        self.linear()
        self.assertEqual(self.title(["groundwork", "001", "002"], ["Ignore build output", "toggle work", "panel work"]), "Users flip the toggle (1/2)")
        self.assertEqual(self.title(["003"], ["test 003", "menu work"], 3, "compose/p-layer-03"), "Open the menu (3/3)")
        self.assertEqual(self.title(["001"], ["test 001", "toggle work"]), "Add the toggle (1/2)")  # part of a story: its task
        self.assertEqual(self.title(["002", "003"], ["panel work", "menu work"]), "Users flip the toggle; Open the menu (1/2)")  # two stories, named

    def test_a_groundwork_layer_is_groundwork_for_the_feature(self):
        self.linear()
        self.assertEqual(self.title(["groundwork"] * 2, ["Test that the briefs read the section " * 5, "Add the stubs"]), "Groundwork for Stacked [PRs] (1/2)")
        self.assertEqual(self.title(["groundwork"], ["Add the stubs"], 3), "Groundwork for Stacked [PRs] (1/3)")

    def test_a_title_past_the_cap_is_cut_at_a_word_and_keeps_its_prefix_and_count(self):
        long = "Test that the wayfinder, change, and explore briefs read the section with linear get, then write the whole section back"
        self.assertEqual(self.title(["groundwork"], [long]), "Test that the wayfinder, change, and explore briefs read the section... (1/2)")
        self.METAS = [{"id": "001", "title": long}, *PrTitle.METAS[1:]]
        self.assertEqual(self.title(["001", "002"], ["toggle work", "panel work"]), "Test that the wayfinder, change, and explore briefs... and 1 more task (1/2)")
        (self.proj / "verify.json").write_text(json.dumps({"branch": "js-2888-react-beside-vue"}))
        self.assertEqual(self.title(["groundwork"], [long]), "JS-2888: Test that the wayfinder, change, and explore briefs read the... (1/2)")
        self.assertEqual(self.title(["groundwork"], ["x" * 100]), "JS-2888: " + "x" * 60 + "... (1/2)")
        self.linear()
        self.assertEqual(self.title(["001"], ["test 001", "toggle work"], 1), "JS-2888: Stacked [PRs]")
        issues = json.loads((self.proj / "results" / "tasks.json").read_text())
        issues["issues"]["NEB-20"]["title"] = "Open the menu from anywhere in the app, with the keyboard or the pointer"
        (self.proj / "results" / "tasks.json").write_text(json.dumps(issues))
        self.assertEqual(self.title(["002", "003"], ["panel work", "menu work"]), "JS-2888: Add the panel and 1 more task (1/2)")  # the stories do not fit


class PrBody(unittest.TestCase):
    """A layer's PR body: Why from its stories, What changed, How it was tested and Tickets, from results files and its own commits."""
    setUp, git, write, commit = Layers.setUp, Layers.git, Layers.write, Layers.commit
    METAS = [{"title": f"Build {m['id']}", "files": [], "after": "", **m} for m in [
             {"id": "001", "linear": "NEB-1", "test": "python3 -m unittest tests.toggle", "protected": ["t004.test", "t001.test"],
              "body": "## Goal\n\nIn `bin/toggle.py` (L10-L40), flip `state`.\n"},
             {"id": "002", "linear": "NEB-2", "test": "python3 -m unittest tests.toggle", "protected": ["t005.test"], "body": "## Goal\nShow the panel.\n"},
             {"id": "003", "linear": "NEB-3", "test": "make menu", "protected": ["t003.test"], "body": "## Goal\nOpen the menu.\n"}]]
    FEATURE = {"id": "NEB-9", "title": "Stacked PRs", "description": "Next: plan it.\n\nFix [compose 7](<https://github.com/o/r/issues/7>) and o/r#8."}
    STORIES = {"NEB-10": {"title": "Users flip the toggle (C2)", "description": "Next: tasks 001 and 002.\n\nFixes [compose 5](<https://github.com/o/r/issues/5>). "
                          "Decisions C1, C2 on NEB-9.\n\nThe toggle is lost on reload, so r\\[\"state\"\\] resets. Later text.\n\n## Acceptance criteria\n\n* it flips"},
               "NEB-20": {"title": "Open the menu", "description": "Card C4 (compose 6). Fixes o/r#6."}}

    def body(self, tasks, units, layers=None, **results):
        issues = {**{k: {**v, "parentId": "NEB-9"} for k, v in self.STORIES.items()},
                  "NEB-1": {"parentId": "NEB-10"}, "NEB-2": {"parentId": "NEB-10"}, "NEB-3": {"parentId": "NEB-20"}}
        results = {"tasks": {"feature": self.FEATURE, "tasks": [], "issues": issues}, "001": {"attempts": 1}, "002": {"attempts": 3}, **results}
        for name, data in results.items():
            (self.proj / "results" / f"{name}.json").write_text(json.dumps(data))
        (self.proj.parent / "linear.json").write_text(json.dumps({"project": "https://linear.app/acme/project/p-1", "team": "Engineering"}))
        shas = []  # units: each of the layer's tasks' commits, as (subject, files, message body)
        for commits in units:
            shas.append([])
            for subject, files, extra in commits:
                for f in files: self.write(f, f"{subject}\n")
                self.git("add", "-A"); self.git("commit", "-q", "--allow-empty", "-m", subject, *(["-m", extra] if extra else [])); shas[-1].append(self.git("rev-parse", "HEAD"))
        l = {"branch": "compose/p-layer-01", "tasks": tasks, "keys": tasks, "lines": 40, "generated": {}, "commits": [c for cs in shas for c in cs], "units": shas}
        stack = [l, *({"branch": f"compose/p-layer-{i:02d}", "tasks": t} for i, t in enumerate(layers or [], 2))]
        with mock.patch.object(fc.fc_stack, "layer_title", return_value=""):  # the title is not this body's concern
            body = fc.fc_stack.layer_pr(self.repo, self.proj, l, 2, self.METAS, stack if layers is not None else ())[1]
        sections, lines = {}, []
        for line in filter(str.strip, body.splitlines()):
            if line.startswith("## "): sections[line[3:]] = lines = []
            else: lines.append(line.strip())
        return sections

    TASK_COMMITS = [[("Cover the toggle", ["t004.test"], ""), ("Build the toggle", ["toggle.src", "t001.test"], "")], [("Build the panel", ["panel.src"], "")]]

    def test_a_task_layer_has_every_section_in_order_from_its_stories_commits_and_results(self):
        s = self.body(["001", "002"], self.TASK_COMMITS)
        self.assertEqual(list(s), ["Why", "What changed", "How it was tested", "Tickets"])
        self.assertEqual(s["What changed"], ["- Build the toggle", "- Build the panel"])  # one line per task, its test commits folded in
        self.assertEqual(s["How it was tested"], ["- `python3 -m unittest tests.toggle`"])  # one line per command
        self.assertEqual(s["Tickets"], ["- [NEB-1](https://linear.app/acme/issue/NEB-1)", "- [NEB-2](https://linear.app/acme/issue/NEB-2)"])

    def test_why_is_the_story_title_and_first_plain_sentence_never_a_brief_card_id_or_linear_escape(self):
        s = self.body(["001", "002"], self.TASK_COMMITS)
        self.assertEqual(s["Why"][0], 'Users flip the toggle. The toggle is lost on reload, so r["state"] resets.')
        why = "\n".join(s["Why"])
        for leak in ("Goal", "bin/toggle.py", "L10", "C1", "C2", "Next", "NEB-9", "\\"):
            self.assertNotIn(leak, why)
        long = {"NEB-10": {"title": "Users flip the toggle", "description": "Why. " * 200}}
        with mock.patch.object(self, "STORIES", {**self.STORIES, **long}):
            s = self.body(["001", "002"], self.TASK_COMMITS)
        self.assertLessEqual(len("\n".join(s["Why"])), 400)

    def test_a_layer_with_several_stories_names_their_titles(self):
        s = self.body(["002", "003"], [self.TASK_COMMITS[1], []], layers=[])
        self.assertEqual(s["Why"][0], "Users flip the toggle. Open the menu.")

    def test_fixes_lands_on_the_layer_that_completes_the_issue_and_part_of_below_it(self):
        s = self.body(["001", "002"], self.TASK_COMMITS, layers=[["003"]])
        self.assertEqual(s["Why"][1:], ["- Fixes o/r#5", "- Part of o/r#7", "- Part of o/r#8"])  # #7 and #8: the feature's, its last task above
        s = self.body(["001", "002", "003"], [*self.TASK_COMMITS, []], layers=[])
        self.assertEqual(s["Why"][1:], ["- Fixes o/r#5", "- Fixes o/r#6", "- Fixes o/r#7", "- Fixes o/r#8"])
        s = self.body(["001"], self.TASK_COMMITS[:1])  # without the stack, every task not here is still to come
        self.assertEqual(s["Why"][1:], ["- Part of o/r#5", "- Part of o/r#7", "- Part of o/r#8"])

    def test_verify_is_reported_last_after_the_checks_it_passed_only_when_its_results_exist(self):
        checks = [{"cmd": "make lint", "exit": 1}, {"cmd": "make all", "exit": 0}, {"cmd": "python3 -m unittest tests.toggle", "exit": 0}]
        s = self.body(["001"], self.TASK_COMMITS[:1], verify={"passed": True, "rounds": [{"checks": checks[:1]}, {"checks": checks}]})
        self.assertEqual(s["How it was tested"], ["- `python3 -m unittest tests.toggle`", "- `make all`", "- compose verify passed"])
        s = self.body(["001"], [[("Cover more", ["t004.test"], "")]], verify={"passed": False, "rounds": [{}, {}]})
        self.assertEqual(s["How it was tested"], ["- `python3 -m unittest tests.toggle`", "- compose verify failed"])
        self.assertEqual(s["What changed"], ["- Build 001"])  # only test commits: the task's own title

    def test_a_groundwork_layer_says_in_one_sentence_what_it_prepares_with_no_issues_tests_or_tickets(self):
        s = self.body(["groundwork", "groundwork"], [[("Ignore build output", ["a.txt"], "Keeps dist out of review.")], [("Pin the toolchain", ["b.txt"], "")]])
        self.assertEqual(s, {"Why": ["Groundwork for Stacked PRs."], "What changed": ["- Ignore build output", "- Pin the toolchain"]})
        s = self.body(["groundwork", "003"], [[("Ignore build output", ["a.txt"], "")], [("Build the menu", ["menu.src"], "")]])
        self.assertEqual(s["Why"][0], "Open the menu.")  # a task in the layer makes it a task layer
        self.assertEqual(s["Tickets"], ["- [NEB-3](https://linear.app/acme/issue/NEB-3)"])


class DeletionBudget(unittest.TestCase):
    """Task 014 (NEB-951): branch_budget counts a whole-file deletion and each delete: path as one line."""

    def repo(self, files):
        r = Path(tempfile.mkdtemp())
        git = lambda *a: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=r, check=True, capture_output=True)
        git("init", "-q", "-b", "main")
        for f, n in files.items():
            (r / f).parent.mkdir(parents=True, exist_ok=True); (r / f).write_text("".join(f"line {i}\n" for i in range(n)))
        git("add", "-A"); git("commit", "-q", "-m", "init")
        return r

    def budget(self, r, allowed, delete=()):
        return fc.fc_gate.branch_budget(r, "main", allowed=allowed, delete=delete)

    def test_deleting_a_400_line_file_the_task_owns_counts_one_line(self):
        r = self.repo({"big.py": 400, "keep.py": 3})
        (r / "big.py").unlink()
        self.assertEqual(self.budget(r, ["big.py"]), (1, [], []))

    def test_a_deleted_delete_directory_counts_one_line_and_its_files_are_not_stray(self):
        r = self.repo({"old/a.py": 100, "old/sub/b.py": 50, "keep.py": 3})
        shutil.rmtree(r / "old")
        self.assertEqual(self.budget(r, [], delete=["old/"]), (1, [], []))

    def test_a_deletion_outside_allowed_and_every_delete_path_is_still_stray(self):
        r = self.repo({"old/a.py": 100, "older.py": 80, "keep.py": 3})
        shutil.rmtree(r / "old"); (r / "older.py").unlink()
        self.assertEqual(self.budget(r, [], delete=["old"]), (2, [], ["older.py"]))

    def test_edits_lockfiles_and_an_emptied_file_count_as_before_beside_a_deletion(self):
        r = self.repo({"a.py": 5, "b.py": 10, "gone.py": 300})
        (r / "a.py").write_text("line 0\nchanged\nline 2\nline 3\nline 4\n"); (r / "b.py").write_text("")
        (r / "yarn.lock").write_text("x\n" * 5000); (r / "gone.py").unlink()
        self.assertEqual(self.budget(r, ["a.py", "b.py", "yarn.lock", "gone.py"]), (2 + 10 + 1, [], []))


class WholeFileDeletion(unittest.TestCase):
    """Task 018: commit_facts counts a file the commit deletes whole as one line."""

    def facts(self, files, change):
        r = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, r, True)
        git = lambda *a: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=r, check=True, capture_output=True)
        git("init", "-q", "-b", "main")
        for f, t in files.items():
            (r / f).parent.mkdir(parents=True, exist_ok=True); (r / f).write_bytes(t if isinstance(t, bytes) else "".join(f"line {i}\n" for i in range(t)).encode())
        git("add", "-A"); git("commit", "-q", "-m", "init")
        change(r); git("add", "-A"); git("commit", "-q", "-m", "change")
        return fc.fc_layers.commit_facts(r, "HEAD")

    def test_a_whole_file_deletion_counts_one_line(self):
        self.assertEqual(self.facts({"old.py": 400, "a.py": 3}, lambda r: (r / "old.py").unlink()), (["old.py"], 1, {}))

    def test_a_deletion_beside_an_edit_counts_one_plus_the_edit(self):
        def change(r):
            (r / "old.py").unlink(); (r / "a.py").write_text((r / "a.py").read_text() + "x\n" * 5)
        files, counted, generated = self.facts({"old.py": 400, "a.py": 3}, change)
        self.assertEqual((sorted(files), counted, generated), (["a.py", "old.py"], 6, {}))

    def test_an_emptied_file_still_counts_every_line(self):
        self.assertEqual(self.facts({"old.py": 400}, lambda r: (r / "old.py").write_text("")), (["old.py"], 400, {}))

    def test_a_deleted_lockfile_stays_generated_with_its_full_count(self):
        got = self.facts({"package-lock.json": 300, "a.py": 3}, lambda r: (r / "package-lock.json").unlink())
        self.assertEqual(got, (["package-lock.json"], 0, {"package-lock.json": 300}))

    def test_each_deleted_file_counts_one_even_in_a_subdirectory_or_binary(self):
        files = {"old/a.py": 100, "old/sub/b.py": 50, "logo.png": bytes(range(256)) * 4, "keep.py": 3}
        got = self.facts(files, lambda r: (shutil.rmtree(r / "old"), (r / "logo.png").unlink()))
        self.assertEqual((sorted(got[0]), got[1], got[2]), (["logo.png", "old/a.py", "old/sub/b.py"], 3, {}))

    def test_a_moved_file_counts_its_old_path_as_one_and_its_new_path_in_full(self):
        got = self.facts({"old.py": 400, "a.py": 3}, lambda r: (r / "old.py").rename(r / "new.py"))
        self.assertEqual((sorted(got[0]), got[1], got[2]), (["new.py", "old.py"], 401, {}))

    def test_a_delete_only_unit_shares_the_layer_of_the_200_line_unit_before_it(self):
        lines = self.facts({"old.py": 400, "a.py": 3}, lambda r: (r / "old.py").unlink())[1]
        layers = fc.fc_layers.group_units([unit("001", 200), unit("002", lines)], 300)
        self.assertEqual([[u["name"] for u in g] for g in layers], [["001", "002"]])


class FailingIds(unittest.TestCase):
    def ids(self, out):
        return fc.fc_gate.FAILING_RE.findall(out)

    def test_a_unittest_summary_line_is_never_a_test_id(self):
        for summary in ("FAILED (failures=3)", "FAILED (errors=2)", "FAILED (failures=1, errors=1)", "FAILED (skipped=2)", "FAILED (failures=1, errors=1, skipped=2)"):
            self.assertEqual(self.ids(f"Ran 5 tests in 0.1s\n\n{summary}\n"), [], summary)

    def test_real_ids_from_each_runner_still_match(self):
        out = ("FAIL: test_x (mod.Class.test_x)\nERROR: test_z (mod.Class.test_z)\nFAILED (failures=1, errors=1)\n"
               "FAILED tests/x.py::test_y - AssertionError\nnot ok 1 - name\n--- FAIL: TestX (0.00s)\n")
        self.assertEqual(self.ids(out), ["test_x (mod.Class.test_x)", "test_z (mod.Class.test_z)", "tests/x.py::test_y - AssertionError", "name", "TestX"])

    def test_the_same_failing_ids_under_a_different_summary_are_no_regression(self):
        state = lambda summary: {"c": {"exit": 1, "failing": sorted(set(self.ids(f"FAIL: test_a (m.C.test_a)\n{summary}\n")))}}
        self.assertEqual(fc.fc_gate.regressions(state("FAILED (errors=3)"), state("FAILED (failures=3)")), [])


if __name__ == "__main__":
    unittest.main()
