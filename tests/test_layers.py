import importlib.machinery, importlib.util, json, os, subprocess, tempfile, unittest
from pathlib import Path
from unittest import mock
import sys
os.environ["FAST_CODING_NO_TREEHOUSE"] = "1"

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "fast_coding.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)

ENV = {"HERDR_ENV": "", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def unit(name, lines):
    return {"name": name, "commits": [], "lines": lines, "generated": {}}


class Grouping(unittest.TestCase):
    def names(self, units, budget):
        return [[u["name"] for u in g] for g in fc.group_units(units, budget)]

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
        self.assertEqual(fc.branch_budget(r, "main", allowed=["package.json", "yarn.lock"]), (1, [], []))


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
        before = fc.gh_pr_text(self.dir, "b")
        return fc.write_pr_text(self.dir, self.dir, "b", before, title, body)

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


class Layers(unittest.TestCase):
    """A project branch with groundwork and every task's test on it, and task branches above it: the layers regroup all of it."""
    def setUp(self):
        self.env = mock.patch.dict(os.environ, ENV); self.env.start(); self.addCleanup(self.env.stop)
        self.repo = Path(tempfile.mkdtemp()).resolve()
        self.git("init", "-q", "-b", "main")
        self.git("remote", "add", "origin", "https://github.com/o/r.git")
        self.write("README.md", "hi\n"); self.commit("init")
        self.git("checkout", "-q", "-b", "fast-coding/p")
        self.proj = self.repo / ".fast-coding" / "p"
        (self.proj / "results").mkdir(parents=True)
        (self.repo / ".git" / "info" / "exclude").write_text("/.fast-coding/\n")
        self.write("lock.txt", ""); self.write("bun.lock", "x\n" * 4000); self.write("setup.txt", "s\n" * 20); self.commit("groundwork one")
        self.write("stub.txt", "s\n" * 20); self.commit("groundwork two")
        tasks = [{"id": t, "protected": [f"t{t}.test"], "files": [f"{t}.src"], "after": ""} for t in ("001", "002", "003")]
        (self.proj / "results" / "tasks.json").write_text(json.dumps({"feature": {}, "tasks": tasks}))
        for t in ("001", "002", "003"):
            self.write(f"t{t}.test", "t\n" * 5); self.commit(f"test {t}")
        self.sizes = {"001": 100, "002": 120, "003": 150}
        for t, base in (("001", "fast-coding/p"), ("002", "fast-coding/p"), ("003", "fast-coding/p")):
            self.git("checkout", "-q", "-b", f"fast/p/{t}", base)
            self.write(f"{t}.src", "c\n" * self.sizes[t]); self.commit(f"task {t}")
            self.git("checkout", "-q", "fast-coding/p")

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
            self.assertTrue(fc.register_stack(self.repo, self.proj, "fast-coding/p"))
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

    def test_a_project_with_a_stored_branch_names_its_layers_from_it(self):
        out = self.stack(branch="fast-coding/p")
        self.assertEqual(self.git("branch", "--list", "fast-coding/p-layer-*", "--format=%(refname:short)").split(), ["fast-coding/p-layer-01", "fast-coding/p-layer-02", "fast-coding/p-layer-03"])
        self.assertEqual(self.layers(), [])
        self.assertTrue(any(l.startswith("layer  layer-01") for l in out))

    def test_a_project_with_layer_branches_already_keeps_their_names(self):
        self.git("branch", "fast/p/layer-09", "main")  # an earlier stack, before the stored branch named layers
        self.stack(branch="fast-coding/p")
        self.assertEqual(self.layers(), ["fast/p/layer-01", "fast/p/layer-02", "fast/p/layer-03"])
        self.assertEqual(json.loads((self.proj / "verify.json").read_text())["layer_prefix"], "fast/p/")
        self.git("branch", "-D", *self.layers())
        self.stack(branch="fast-coding/p", layer_prefix="fast/p/")  # recorded, so no branch is needed to remember it
        self.assertEqual(len(self.layers()), 3)

    def test_layer_branches_on_the_remote_alone_keep_their_names(self):
        self.git("update-ref", "refs/remotes/origin/fast/p/layer-01", "main")
        self.stack(branch="fast-coding/p")
        self.assertEqual(len(self.layers()), 3)

    def test_the_first_build_records_the_names_it_chose(self):
        self.stack(branch="fast-coding/p")
        self.assertEqual(json.loads((self.proj / "verify.json").read_text())["layer_prefix"], "fast-coding/p-")

    def test_a_layers_pr_is_titled_from_its_tasks_and_the_jira_key(self):
        (self.proj / "verify.json").write_text(json.dumps({"branch": "js-2888-react-beside-vue"}))
        metas = [{"id": "001", "title": "001: Add the toggle"}, {"id": "002", "title": "Add the panel"}]
        l = {"branch": "js-2888-react-beside-vue-layer-01", "tasks": ["001", "002"], "lines": 230, "generated": {}}
        title, body = fc.layer_pr(self.proj, l, 4, 300, metas)
        self.assertEqual(title, "JS-2888: Add the toggle, Add the panel (1/4)")
        self.assertEqual(body, "- Add the toggle\n- Add the panel\n\ntask 001, 002: 230 lines")
        (self.proj / "verify.json").write_text("{}")
        self.assertEqual(fc.layer_pr(self.proj, {**l, "branch": "fast/p/layer-02"}, 4, 300, metas)[0], "Add the toggle, Add the panel (2/4)")

    def test_a_task_over_the_budget_is_never_split(self):
        out = self.stack(review_layer_lines=130)
        self.assertEqual(len(self.layers()), 4)
        self.assertEqual(self.changed("fast/p/layer-04", "fast/p/layer-03"), {"t003.test", "003.src"})
        self.assertIn("task 003: 155 lines; over the 130-line budget", out[-1])

    def test_a_submitted_stack_keeps_each_task_in_its_layer_when_sizes_change(self):
        self.stack(review_layer_lines=300)
        fc.record_layers(self.proj, [{"branch": b, "tasks": t} for b, t in (("fast/p/layer-01", ["groundwork"]), ("fast/p/layer-02", ["001", "002"]), ("fast/p/layer-03", ["003"]))])
        self.git("checkout", "-q", "fast/p/003")
        self.write("003.src", "c\n"); self.commit("shrink 003")  # 003 now fits with 001 and 002, so a regroup would merge layers 02 and 03
        self.git("checkout", "-q", "fast-coding/p")
        self.stack(review_layer_lines=300)
        self.assertEqual(self.layers(), ["fast/p/layer-01", "fast/p/layer-02", "fast/p/layer-03"])
        self.assertEqual(self.changed("fast/p/layer-03", "fast/p/layer-02"), {"t003.test", "003.src"})

    def test_a_task_new_since_the_submit_gets_a_layer_above(self):
        self.stack()
        fc.record_layers(self.proj, [{"branch": b, "tasks": t} for b, t in (("fast/p/layer-01", ["groundwork"]), ("fast/p/layer-02", ["001"]))])
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
        wt = fc.fc_worktree.stack_worktree(self.repo, self.proj, "fast-coding/p")
        subprocess.run(["git", "checkout", "-q", "fast/p/layer-02"], cwd=wt, check=True)
        data = json.loads(subprocess.run(["gh", "stack", "view", "--json"], cwd=wt, capture_output=True, text=True).stdout)
        self.assertEqual(data["trunk"], "main")
        self.assertEqual([b["name"] for b in data["branches"]], self.layers())


if __name__ == "__main__":
    unittest.main()
