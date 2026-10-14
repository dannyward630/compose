import importlib.machinery, importlib.util, json, os, subprocess, tempfile, unittest
from pathlib import Path
from unittest import mock
os.environ["FAST_CODING_NO_TREEHOUSE"] = "1"

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "fast-coding")))
fc = importlib.util.module_from_spec(_spec)
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
            self.assertTrue(fc.GENERATED_RE.search(f), f)
        for f in ("src/lock.ts", "locksmith.py", "docs/bun.lock.md"):
            self.assertFalse(fc.GENERATED_RE.search(f), f)

    def test_a_task_branch_does_not_count_its_lockfile_toward_the_limit(self):
        r = Path(tempfile.mkdtemp())
        git = lambda *a: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=r, check=True, capture_output=True)
        git("init", "-q", "-b", "main"); git("commit", "-q", "--allow-empty", "-m", "init")
        (r / "package.json").write_text('{"vite": "8"}\n'); (r / "yarn.lock").write_text("x\n" * 5000)
        self.assertEqual(fc.branch_budget(r, "main", allowed=["package.json", "yarn.lock"]), (1, [], []))


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
        with mock.patch.object(fc, "say", out.append):
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

    def test_a_project_with_a_stored_branch_names_its_layers_from_it(self):
        out = self.stack(branch="fast-coding/p")
        self.assertEqual(self.git("branch", "--list", "fast-coding/p-layer-*", "--format=%(refname:short)").split(), ["fast-coding/p-layer-01", "fast-coding/p-layer-02", "fast-coding/p-layer-03"])
        self.assertEqual(self.layers(), [])
        self.assertTrue(any(l.startswith("layer  layer-01") for l in out))

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

    def test_a_rebuild_from_unchanged_commits_keeps_the_hashes(self):
        self.stack()
        before = self.git("rev-parse", "fast/p/layer-01", "fast/p/layer-02")
        self.stack()
        self.assertEqual(self.git("rev-parse", "fast/p/layer-01", "fast/p/layer-02"), before)

    def test_the_gh_stack_is_the_layers_on_the_real_base(self):
        self.stack()
        wt = fc.stack_worktree(self.repo, self.proj, "fast-coding/p")
        subprocess.run(["git", "checkout", "-q", "fast/p/layer-02"], cwd=wt, check=True)
        data = json.loads(subprocess.run(["gh", "stack", "view", "--json"], cwd=wt, capture_output=True, text=True).stdout)
        self.assertEqual(data["trunk"], "main")
        self.assertEqual([b["name"] for b in data["branches"]], self.layers())


if __name__ == "__main__":
    unittest.main()
