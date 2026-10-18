import hermetic  # first: no test sees the real home
import importlib.machinery, importlib.util, json, os, subprocess, tempfile, unittest
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
        self.assertEqual(fc.fc_implement.branch_budget(r, "main", allowed=["package.json", "yarn.lock"]), (1, [], []))


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
        before = fc.fc_layers.gh_pr_text(self.dir, "b")
        return fc.fc_layers.write_pr_text(self.dir, self.dir, "b", before, title, body)

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
        tasks = [{"id": t, "protected": [f"t{t}.test"], "files": [f"{t}.src"], "after": ""} for t in ("001", "002", "003")]
        (self.proj / "results" / "tasks.json").write_text(json.dumps({"feature": {}, "tasks": tasks}))
        for t in ("001", "002", "003"):
            self.write(f"t{t}.test", "t\n" * 5); self.commit(f"test {t}")
        self.sizes = {"001": 100, "002": 120, "003": 150}
        for t, base in (("001", "compose/p"), ("002", "compose/p"), ("003", "compose/p")):
            self.git("checkout", "-q", "-b", f"fast/p/{t}", base)
            self.write(f"{t}.src", "c\n" * self.sizes[t]); self.commit(f"task {t}")
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
            self.assertTrue(fc.fc_layers.register_stack(self.repo, self.proj, "compose/p"))
        return out

    def changed(self, branch, below):
        return set(self.git("diff", "--name-only", below, branch).splitlines())

    def layers(self):
        return self.git("branch", "--list", "fast/p/layer-*", "--format=%(refname:short)").split()

    def test_groundwork_is_its_own_layer_and_each_test_lands_with_its_task(self):
        out = self.stack()  # default budget 300: tasks with their tests are 105, 125 and 155 lines
        self.assertEqual(self.layers(), ["fast/p/layer-01", "fast/p/layer-02", "fast/p/layer-03"])
        self.assertEqual(self.changed("fast/p/layer-01", "main"), {"lock.txt", "bun.lock", "setup.txt", "stub.txt"})
        self.assertEqual(self.changed("fast/p/layer-02", "fast/p/layer-01"), {"t001.test", "001.src", "t002.test", "002.src"})
        self.assertEqual(self.changed("fast/p/layer-03", "fast/p/layer-02"), {"t003.test", "003.src"})
        self.assertEqual(self.git("diff", "fast/p/layer-03", "fast/p/003"), "")  # the layers add up to the project's tree
        notes = [l for l in out if l.startswith("layer ")]
        self.assertIn("groundwork x2: 40 lines; generated, not counted: bun.lock (4000 lines)", notes[0])
        self.assertIn("task 001, 002: 230 lines", notes[1])

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
        self.assertEqual(self.layers(), ["fast/p/layer-01", "fast/p/layer-02", "fast/p/layer-03"])
        self.assertEqual(self.changed("fast/p/layer-02", "fast/p/layer-01"), {"t001.test", "001.src", "t002.test", "002.src", "shared.test"})
        self.assertEqual(self.git("show", "fast/p/layer-02:shared.test"), "a\n" * 5 + "b\n" * 4 + "b")
        self.assertEqual(self.git("diff", "fast/p/layer-03", "fast/p/003"), "")

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
        self.assertEqual(self.layers(), ["fast/p/layer-01", "fast/p/layer-02", "fast/p/layer-03", "fast/p/layer-04"])
        self.assertEqual(self.changed("fast/p/layer-02", "fast/p/layer-01"), {"t001.test", "001.src", "t002.test", "002.src"})
        self.assertEqual(self.changed("fast/p/layer-03", "fast/p/layer-02"), {"t002.test", "shared.test"})
        self.assertEqual(self.changed("fast/p/layer-04", "fast/p/layer-03"), {"t003.test", "003.src", "shared.test"})
        self.assertIn("layer-03  groundwork x1: 2 lines", [l for l in out if l.startswith("layer ")][2])
        self.assertEqual(self.git("diff", "fast/p/layer-04", "fast/p/003"), "")

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
        self.assertEqual(self.layers(), ["fast/p/layer-01", "fast/p/layer-02", "fast/p/layer-03"])
        self.assertEqual(self.git("show", "fast/p/layer-02:shared.test"), "a\n" * 4 + "a")
        self.assertEqual(self.changed("fast/p/layer-03", "fast/p/layer-02"), {"t003.test", "003.src", "shared.test"})
        self.assertEqual(self.git("diff", "fast/p/layer-03", "fast/p/003"), "")

    def test_a_project_with_layer_branches_already_keeps_their_names(self):
        self.git("branch", "fast/p/layer-09", "main")  # an earlier stack, before the stored branch named layers
        self.stack(branch="compose/p")
        self.assertEqual(self.layers(), ["fast/p/layer-01", "fast/p/layer-02", "fast/p/layer-03"])
        self.assertEqual(json.loads((self.proj / "verify.json").read_text())["layer_prefix"], "fast/p/")
        self.git("branch", "-D", *self.layers())
        self.stack(branch="compose/p", layer_prefix="fast/p/")  # recorded, so no branch is needed to remember it
        self.assertEqual(len(self.layers()), 3)

    def test_layer_branches_on_the_remote_alone_keep_their_names(self):
        self.git("update-ref", "refs/remotes/origin/fast/p/layer-01", "main")
        self.stack(branch="compose/p")
        self.assertEqual(len(self.layers()), 3)

    def test_a_task_over_the_budget_is_never_split(self):
        out = self.stack(review_layer_lines=130)
        self.assertEqual(len(self.layers()), 4)
        self.assertEqual(self.changed("fast/p/layer-04", "fast/p/layer-03"), {"t003.test", "003.src"})
        self.assertIn("task 003: 155 lines; over the 130-line budget", out[-1])

    def test_a_submitted_stack_keeps_each_task_in_its_layer_when_sizes_change(self):
        self.stack(review_layer_lines=300)
        fc.fc_layers.record_layers(self.proj, [{"branch": b, "tasks": t} for b, t in (("fast/p/layer-01", ["groundwork"]), ("fast/p/layer-02", ["001", "002"]), ("fast/p/layer-03", ["003"]))])
        self.git("checkout", "-q", "fast/p/003")
        self.write("003.src", "c\n"); self.commit("shrink 003")  # 003 now fits with 001 and 002, so a regroup would merge layers 02 and 03
        self.git("checkout", "-q", "compose/p")
        self.stack(review_layer_lines=300)
        self.assertEqual(self.layers(), ["fast/p/layer-01", "fast/p/layer-02", "fast/p/layer-03"])
        self.assertEqual(self.changed("fast/p/layer-03", "fast/p/layer-02"), {"t003.test", "003.src"})

    def test_a_task_new_since_the_submit_gets_a_layer_above(self):
        self.stack()
        fc.fc_layers.record_layers(self.proj, [{"branch": b, "tasks": t} for b, t in (("fast/p/layer-01", ["groundwork"]), ("fast/p/layer-02", ["001"]))])
        self.stack()
        self.assertEqual(self.layers(), ["fast/p/layer-01", "fast/p/layer-02", "fast/p/layer-03"])
        self.assertEqual(self.changed("fast/p/layer-02", "fast/p/layer-01"), {"t001.test", "001.src"})
        self.assertEqual(self.changed("fast/p/layer-03", "fast/p/layer-02"), {"t002.test", "002.src", "t003.test", "003.src"})

    def test_a_rebuild_from_unchanged_commits_keeps_the_hashes(self):
        self.stack()
        before = self.git("rev-parse", "fast/p/layer-01", "fast/p/layer-02")
        self.stack()
        self.assertEqual(self.git("rev-parse", "fast/p/layer-01", "fast/p/layer-02"), before)

    def test_the_gh_stack_is_the_layers_on_the_real_base(self):
        self.stack()
        wt = fc.fc_worktree.stack_worktree(self.repo, self.proj, "compose/p")
        subprocess.run(["git", "checkout", "-q", "fast/p/layer-02"], cwd=wt, check=True)
        data = json.loads(subprocess.run(["gh", "stack", "view", "--json"], cwd=wt, capture_output=True, text=True).stdout)
        self.assertEqual(data["trunk"], "main")
        self.assertEqual([b["name"] for b in data["branches"]], self.layers())


class LayerNames(unittest.TestCase):
    """The Layers project with its task branches under the task prefix: the layers and the chain take their names from it."""
    setUp, git, write, commit, stack, changed = Layers.setUp, Layers.git, Layers.write, Layers.commit, Layers.stack, Layers.changed

    def rename(self, prefix):
        for t in ("001", "002", "003"):
            self.git("branch", "-m", f"fast/p/{t}", f"{prefix}{t}")

    def layers(self, prefix="compose/p-"):
        return self.git("branch", "--list", f"{prefix}layer-*", "--format=%(refname:short)").split()

    def test_a_new_project_cuts_its_task_branches_into_layers_named_from_its_branch(self):
        self.rename("compose/p-")
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
        self.rename("compose/p-")
        self.git("checkout", "-q", "-B", "compose/p-001", "compose/p-003")
        self.write("001.src", "c\n" * 100); self.commit("task 001 on 003")
        self.git("checkout", "-q", "compose/p")
        out = self.stack()
        self.assertEqual([l for l in out if "STOP" in l], [])
        self.assertEqual(self.changed("compose/p-layer-03", "compose/p-layer-02"), {"t001.test", "001.src"})
        self.assertEqual(self.git("diff", "compose/p-layer-03", "compose/p-001"), "")

    def test_a_replaced_tip_is_dropped_from_the_layer_above_and_its_ref_deleted(self):
        self.rename("compose/p-")
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

    def test_a_legacy_project_keeps_fast_names_unless_a_prefix_is_recorded(self):
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
    """A layer's PR is titled from its commits: one commit's subject, else its first task's title or first commit's subject and N more."""
    setUp, git, write, commit, stack = Layers.setUp, Layers.git, Layers.write, Layers.commit, Layers.stack
    METAS = [{"id": "001", "title": "001: Add the toggle"}, {"id": "002", "title": "Add the panel"}, {"id": "003", "title": "Add the menu"}]

    def title(self, tasks, subjects, n=2, branch="compose/p-layer-01"):
        commits = []
        for s in subjects:
            self.git("commit", "-q", "--allow-empty", "-m", s); commits.append(self.git("rev-parse", "HEAD"))
        l = {"branch": branch, "tasks": tasks, "keys": tasks, "lines": 40, "generated": {}, "commits": commits}
        with mock.patch.object(fc.fc_layers, "layer_body", return_value=""):  # the body is not this title's concern
            return fc.fc_layers.layer_pr(self.repo, self.proj, l, n, 300, self.METAS)[0]

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
        self.assertEqual(self.title(["groundwork"] * 3, ["Ignore build output", "Pin the toolchain", "Add a lint step"]), "Ignore build output and 2 more (1/2)")

    def test_a_task_layer_is_its_first_tasks_title_and_n_more_counting_only_its_other_tasks(self):
        subjects = ["test 001", "toggle work", "test 002", "panel work", "menu work"]
        self.assertEqual(self.title(["001", "002", "003"], subjects, 4, "compose/p-layer-02"), "Add the toggle and 2 more (2/4)")
        self.assertEqual(self.title(["001"], ["test 001", "toggle work"]), "Add the toggle (1/2)")
        self.assertEqual(self.title(["groundwork", "002", "003"], ["Ignore build output", "panel work", "menu work"]), "Add the panel and 1 more (1/2)")

    def test_a_jira_key_on_the_project_branch_prefixes_the_title(self):
        (self.proj / "verify.json").write_text(json.dumps({"branch": "js-2888-react-beside-vue"}))
        self.assertEqual(self.title(["001", "002"], ["toggle work", "panel work"], 4, "js-2888-react-beside-vue-layer-03"), "JS-2888: Add the toggle and 1 more (3/4)")
        self.assertEqual(self.title(["groundwork"], ["Ignore build output"]), "JS-2888: Ignore build output (1/2)")


class PrBody(unittest.TestCase):
    """A layer's PR body: Why, What changed, How it was tested and Tickets, from results files and the layer's own commits."""
    setUp, git, write, commit = Layers.setUp, Layers.git, Layers.write, Layers.commit
    METAS = [{"title": f"Task {m['id']}", "files": [], "after": "", **m} for m in [
             {"id": "001", "linear": "NEB-1", "test": "python3 -m unittest tests.toggle", "protected": ["t004.test", "t001.test"],
              "body": "## Goal\n\nUsers flip the toggle.\n\n## Acceptance criteria\n\n* it flips\n"},
             {"id": "002", "linear": "NEB-2", "test": "npm test", "protected": ["t005.test"], "body": "## Goal\nShow the panel.\n"},
             {"id": "003", "linear": "NEB-3", "test": "make menu", "protected": ["t003.test"], "body": "## Goal\nOpen the menu.\n"}]]

    def body(self, tasks, commits, **results):
        results = {"tasks": {"feature": {"id": "ENG-1", "title": "Stacked PRs"}, "tasks": []}, "001": {"attempts": 1}, "002": {"attempts": 3}, **results}
        for name, data in results.items():
            (self.proj / "results" / f"{name}.json").write_text(json.dumps(data))
        shas = []
        for subject, files, extra in commits:
            for f in files: self.write(f, f"{subject}\n")
            self.git("add", "-A"); self.git("commit", "-q", "--allow-empty", "-m", subject, *(["-m", extra] if extra else [])); shas.append(self.git("rev-parse", "HEAD"))
        l = {"branch": "compose/p-layer-01", "tasks": tasks, "keys": tasks, "lines": 40, "generated": {}, "commits": shas}
        with mock.patch.object(fc.fc_layers, "layer_title", return_value=""):  # the title is not this body's concern
            body = fc.fc_layers.layer_pr(self.repo, self.proj, l, 2, 300, self.METAS)[1]
        sections, lines = {}, []
        for line in filter(str.strip, body.splitlines()):
            if line.startswith("## "): sections[line[3:]] = lines = []
            else: lines.append(line.strip().lstrip("-* "))
        return sections, fc.fc_layers.layer_note(l, 300)

    TASK_COMMITS = [("Cover the toggle", ["t004.test"], ""), ("Build the toggle", ["toggle.src", "t001.test"], ""), ("Build the panel", ["panel.src"], "")]

    def test_a_task_layer_has_every_section_in_order_from_its_tasks_commits_and_results(self):
        s, note = self.body(["001", "002"], self.TASK_COMMITS)
        self.assertEqual(list(s), ["Why", "What changed", "How it was tested", "Tickets"])
        self.assertIn("Stacked PRs", s["Why"][0])
        self.assertEqual(s["Why"][1:], ["Users flip the toggle.", "Show the panel."])
        self.assertEqual(s["What changed"], ["Cover the toggle", "Build the toggle", "Build the panel", note])
        how = s["How it was tested"]
        self.assertIn("passed, 1 attempt", next(x for x in how if "`python3 -m unittest tests.toggle`" in x))
        self.assertIn("passed, 3 attempt", next(x for x in how if "`npm test`" in x))
        self.assertTrue(any("t004.test" in x for x in how))  # added by the layer and protected; a modified or unprotected file is not a test it adds
        self.assertFalse(any(f in x for x in how for f in ("t001.test", "toggle.src", "t003.test", "verify")))
        self.assertEqual(s["Tickets"], ["NEB-1", "NEB-2"])

    def test_verify_is_reported_last_with_its_round_count_only_when_its_results_exist(self):
        s, _ = self.body(["001"], self.TASK_COMMITS[:1], verify={"passed": True, "rounds": [{}]})
        self.assertIn("verify passed in 1 round", s["How it was tested"][-1])
        s, _ = self.body(["001"], [("Cover more", ["t004.test"], "")], verify={"passed": False, "rounds": [{}, {}]})
        self.assertIn("verify failed after 2 round", s["How it was tested"][-1])

    def test_a_groundwork_layer_says_whose_groundwork_it_is_with_its_commit_bodies_and_no_tests_or_tickets(self):
        s, note = self.body(["groundwork", "groundwork"], [("Ignore build output", ["a.txt"], "Keeps dist out of review."), ("Pin the toolchain", ["b.txt"], "")])
        self.assertEqual(s, {"Why": ["Groundwork for Stacked PRs.", "Keeps dist out of review."], "What changed": ["Ignore build output", "Pin the toolchain", note]})
        s, _ = self.body(["groundwork", "002"], [("Ignore build output", ["a.txt"], ""), ("Build the panel", ["panel.src"], "")])
        self.assertEqual(s["Why"][1:], ["Show the panel."])  # a task in the layer makes it a task layer
        self.assertEqual(s["Tickets"], ["NEB-2"])


if __name__ == "__main__":
    unittest.main()
