import hermetic  # first: no test sees the real home
import argparse, importlib.machinery, importlib.util, io, json, os, subprocess, tempfile, unittest
from contextlib import redirect_stdout
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

# gh without a login or a network: `gh stack` keeps its stack in the repo's git dir and pushes to the local bare origin; `gh pr` keeps
# the pull requests in a state file, reads their heads from that origin, and merges by squash into it. Every call is logged.
FAKE_GH = """#!/usr/bin/env python3
import json, os, subprocess, sys
from pathlib import Path
a, origin, state_f = sys.argv[1:], os.environ["FAKE_ORIGIN"], Path(os.environ["FAKE_GH_STATE"])
st = json.loads(state_f.read_text()) if state_f.exists() else {"prs": {}, "log": []}
st["log"].append(" ".join(a))
git = lambda *x: subprocess.run(["git", *x], capture_output=True, text=True).stdout.strip()
ogit = lambda *x: git("--git-dir", origin, *x)
def done(code=0):
    state_f.write_text(json.dumps(st)); sys.exit(code)
def find(x):
    for n, p in st["prs"].items():
        if x in (n, p["branch"]): return n, p
    return None, None
head = lambda p: ogit("rev-parse", "--verify", "-q", "refs/heads/" + p["branch"])
if a[0] == "stack":
    f = Path(git("rev-parse", "--path-format=absolute", "--git-common-dir")) / "fake-gh-stack.json"
    s = json.loads(f.read_text()) if f.exists() else None
    if a[1] == "init":
        f.write_text(json.dumps({"trunk": a[a.index("--base") + 1], "branches": [{"name": b} for b in a[4:]]}))
    elif a[1] == "view" and s and git("branch", "--show-current") in [b["name"] for b in s["branches"]]:
        print(json.dumps(s))
    elif a[1] == "unstack":
        f.unlink(missing_ok=True)
    elif a[1] == "submit" and s:
        below = s["trunk"]
        for b in s["branches"]:
            subprocess.run(["git", "push", "-q", "--force", "origin", b["name"]], check=True)
            if not find(b["name"])[1]:
                st["prs"][str(len(st["prs"]) + 1)] = {"branch": b["name"], "base": below, "state": "OPEN", "draft": True, "checks": ["pass"], "title": "t", "body": "b"}
            below = b["name"]
    else:
        done(1)
    done()
n, p = find(a[2]) if len(a) > 2 else (None, None)
if a[:2] == ["pr", "view"]:
    if not p: done(1)
    print(json.dumps({"number": int(n), "baseRefName": p["base"], "state": p["state"], "isDraft": p["draft"], "headRefOid": head(p),
                      "url": "https://github.com/o/r/pull/" + n, "mergeStateStatus": "BEHIND" if p.get("behind") else "CLEAN", "title": p["title"], "body": p["body"]}))
elif a[:2] == ["pr", "edit"]:
    if "--base" in a: p["base"] = a[a.index("--base") + 1]
    else: p["title"], p["body"] = a[a.index("--title") + 1], a[a.index("--body") + 1]
elif a[:2] == ["pr", "ready"]:
    p["draft"] = False
elif a[:2] == ["pr", "checks"]:
    seq = p["checks"]; cur = seq.pop(0) if len(seq) > 1 else seq[0]
    if cur == "none":
        print("no required checks reported on the branch", file=sys.stderr); done(1)
    print(json.dumps([{"name": "ci", "bucket": cur}])); done({"pass": 0, "pending": 8, "fail": 1}[cur])
elif a[:2] == ["pr", "update-branch"]:
    p["behind"] = False
    ogit("update-ref", "refs/heads/" + p["branch"], ogit("commit-tree", head(p) + "^{tree}", "-p", head(p), "-m", "update branch"))
elif a[:2] == ["pr", "merge"]:
    if p.get("refuse"):
        print(p["refuse"], file=sys.stderr); done(1)
    tree = head(p) + "^{tree}"
    if p.get("extra"):  # the base also gains a file of its own with this merge
        env = {**os.environ, "GIT_INDEX_FILE": origin + "/fake-index"}
        run = lambda *x, **k: subprocess.run(["git", "--git-dir", origin, *x], capture_output=True, text=True, env=env, **k).stdout.strip()
        run("read-tree", tree)
        blob = run("hash-object", "-w", "--stdin", input=p["extra"][1])
        run("update-index", "--add", "--cacheinfo", "100644," + blob + "," + p["extra"][0])
        tree = run("write-tree")
    ogit("update-ref", "refs/heads/" + p["base"], ogit("commit-tree", tree, "-p", ogit("rev-parse", "refs/heads/" + p["base"]), "-m", "PR " + n))
    p["state"] = "MERGED"
else:
    done(1)
done()
"""


class Ship(unittest.TestCase):
    """A project with groundwork and three tasks, stacked into three layers, a local bare origin, and a fake gh."""
    def setUp(self):
        bin_ = Path(tempfile.mkdtemp()).resolve()
        (bin_ / "gh").write_text(FAKE_GH); (bin_ / "gh").chmod(0o755)
        self.origin = Path(tempfile.mkdtemp()).resolve()
        self.state = bin_ / "state.json"
        self.env = mock.patch.dict(os.environ, {**ENV, "PATH": f"{bin_}:{os.environ['PATH']}", "FAKE_ORIGIN": str(self.origin), "FAKE_GH_STATE": str(self.state)})
        self.env.start(); self.addCleanup(self.env.stop)
        for patch in (mock.patch.object(fc.fc_ship, "LAND_POLL", 0), mock.patch.object(fc.fc_ship, "LAND_SETTLE", 0)):
            patch.start(); self.addCleanup(patch.stop)
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.origin)], check=True)
        self.repo = Path(tempfile.mkdtemp()).resolve()
        self.git("init", "-q", "-b", "main")
        self.git("remote", "add", "origin", str(self.origin))
        self.write("README.md", "hi\n"); self.commit("init")
        self.git("push", "-q", "-u", "origin", "main")
        self.git("checkout", "-q", "-b", "compose/p")
        self.proj = self.repo / ".compose" / "p"
        (self.proj / "results").mkdir(parents=True)
        (self.repo / ".git" / "info" / "exclude").write_text("/.compose/\n")
        self.write("setup.txt", "s\n" * 20); self.commit("Add the setup files")
        tasks = [{"id": t, "protected": [f"t{t}.test"], "files": [f"{t}.src"], "after": "", "test": f"make {t}", "title": f"Build {t}", "linear": f"ENG-{t}", "body": f"## Goal\nBuild {t}.\n"}
                 for t in ("001", "002", "003")]
        (self.proj / "results" / "tasks.json").write_text(json.dumps({"feature": {}, "tasks": tasks}))
        for t in ("001", "002", "003"):
            (self.proj / "results" / f"{t}.json").write_text(json.dumps({"status": "passed"}))  # done: a submit pushes their layers
        for t in ("001", "002", "003"):
            self.write(f"t{t}.test", "t\n" * 5); self.commit(f"Cover {t}")
        for t, size in (("001", 100), ("002", 120), ("003", 150)):
            self.git("checkout", "-q", "-b", f"compose/p-{t}", "compose/p")
            self.write(f"{t}.src", "c\n" * size); self.commit(f"Build {t}")
            self.git("checkout", "-q", "compose/p")
        self.config()

    def git(self, *a):
        return subprocess.run(["git", *a], cwd=self.repo, check=True, capture_output=True, text=True).stdout.strip()

    def write(self, name, text):
        (self.repo / name).write_text(text)

    def commit(self, msg):
        self.git("add", "-A"); self.git("commit", "-qm", msg)

    def config(self, **cfg):
        (self.proj / "verify.json").write_text(json.dumps({"review_base": "main", **cfg}))

    def args(self, **kw):
        return argparse.Namespace(repo=str(self.repo), project="p", trunk="compose/p", **{"update": False, **kw})

    def run_cmd(self, fn, **kw):
        """Run a command; its said lines, printed text, and exit code (0 when it returned)."""
        out, buf, code = [], io.StringIO(), 0
        with mock.patch.object(fc.fc_core, "say", out.append), redirect_stdout(buf):
            try:
                fn(self.args(**kw))
            except SystemExit as e:
                code = e.code
        return out + buf.getvalue().splitlines(), code

    def submit(self):
        return self.run_cmd(fc.fc_ship.cmd_stack, submit=True)

    def log(self):
        return json.loads(self.state.read_text())["log"] if self.state.exists() else []

    def prs(self):
        return json.loads(self.state.read_text())["prs"]

    def set_pr(self, n, **kw):
        st = json.loads(self.state.read_text()); st["prs"][str(n)].update(kw); self.state.write_text(json.dumps(st))

    def origin_has(self, ref):
        return subprocess.run(["git", "--git-dir", str(self.origin), "rev-parse", "--verify", "-q", ref], capture_output=True).returncode == 0

    def subjects(self, branch):
        return self.git("log", "--format=%s", f"main..{branch}").splitlines()

    def land(self, **kw):
        return self.run_cmd(fc.fc_ship.cmd_land, **{"yes": True, "method": None, "timeout": 1, **kw})


class LayerChecks(Ship):
    def test_a_failing_layer_refuses_the_submit_and_is_named_with_nothing_pushed(self):
        self.config(checks=["! test -f 002.src"])  # layer 1 holds the setup files and passes; layer 2 has 002.src
        out, code = self.submit()
        self.assertEqual(code, 1)
        stop = [l for l in out if "STOP" in l]
        self.assertEqual(len(stop), 1)
        self.assertIn("layer 2 of 3 (compose/p-layer-02) fails `! test -f 002.src` on its own tree", stop[0])
        self.assertIn("Nothing was pushed", stop[0])
        self.assertTrue(any("layers ok" in l and "compose/p-layer-01" in l for l in out))
        self.assertFalse(any("stack submit" in c for c in self.log()))
        self.assertFalse(self.origin_has("refs/heads/compose/p-layer-01"))
        self.assertFalse((self.proj / "layers.json").exists())

    def test_every_layer_runs_the_checks_once_and_an_unchanged_layer_is_not_run_again(self):
        counter = Path(tempfile.mkdtemp()) / "runs"
        self.config(checks=[f"echo run >> {counter}"])
        out, code = self.submit()
        self.assertEqual(code, 0, out)
        self.assertEqual(len(counter.read_text().splitlines()), 3)
        self.assertTrue(any("stack submit --auto" in c for c in self.log()))
        self.assertTrue(self.origin_has("refs/heads/compose/p-layer-03"))
        out, code = self.submit()
        self.assertEqual(len(counter.read_text().splitlines()), 3)
        self.assertEqual(len([l for l in out if "unchanged since its checks passed" in l]), 3)
        self.config(checks=[f"echo run >> {counter}", "true"])  # other checks: every layer is checked again
        self.submit()
        self.assertEqual(len(counter.read_text().splitlines()), 6)

    def test_a_layer_is_checked_on_its_own_tree_not_the_top(self):
        self.config(checks=["test -f 003.src"])  # only the top layer has it
        out, code = self.submit()
        self.assertEqual(code, 1)
        self.assertIn("layer 1 of 3 (compose/p-layer-01) fails `test -f 003.src`", "\n".join(out))

    def test_a_stack_preview_and_a_project_without_checks_run_none(self):
        counter = Path(tempfile.mkdtemp()) / "runs"
        self.config(checks=[f"echo run >> {counter}"])
        self.run_cmd(fc.fc_ship.cmd_stack, submit=False)
        self.assertFalse(counter.exists())
        self.config()
        out, code = self.submit()
        self.assertEqual(code, 0)
        self.assertTrue(any("no checks in verify.json" in l for l in out))
        self.assertTrue(any("stack submit --auto" in c for c in self.log()))


class Reword(Ship):
    def test_a_commit_message_that_names_the_process_is_fixed_when_the_layer_is_built(self):
        self.git("checkout", "-q", "compose/p-001")
        self.git("commit", "-q", "--amend", "-m", "task 001: wire compose verify\n\nDone by the implementer.\nIndex the title.")
        self.git("checkout", "-q", "compose/p")
        out, code = self.run_cmd(fc.fc_ship.cmd_stack, submit=False)
        self.assertEqual(code, 0)
        self.assertIn("Update 001.src", self.subjects("compose/p-layer-02"))
        self.assertNotIn("task 001: wire compose verify", self.subjects("compose/p-layer-02"))
        self.assertTrue(any("stack  note" in l and "wire compose verify" in l and "mentions the process (`task 001`)" in l for l in out))
        self.assertEqual(self.git("log", "-1", "--format=%s", "compose/p-001"), "task 001: wire compose verify")  # the task branch is left alone
        body = self.git("log", "--format=%B", "--grep=^Update 001.src", "compose/p-layer-02")
        self.assertIn("Index the title.", body)
        self.assertNotIn("implementer", body)

    def test_reword_lists_the_layer_commits_and_flags_the_ones_that_break_the_rules(self):
        self.run_cmd(fc.fc_ship.cmd_stack, submit=False)
        self.config(commit_convention={"types": ["feat", "fix"], "example": "feat: x"})
        out, code = self.run_cmd(fc.fc_ship.cmd_reword, set=None, as_is=False)
        self.assertEqual(code, 0)
        listed = [l for l in out if l.startswith("  ")]
        self.assertEqual(len(listed), 7)  # setup, three tests, three tasks
        self.assertTrue(all("no type prefix" in l for l in listed))
        self.assertFalse(self.prs())

    def test_set_rewords_one_commit_keeps_the_trees_and_never_pushes(self):
        self.run_cmd(fc.fc_ship.cmd_stack, submit=False)
        tips = {b: self.git("rev-parse", b) for b in ("compose/p-layer-01", "compose/p-layer-02", "compose/p-layer-03")}
        sha = self.git("log", "-1", "--format=%H", "--grep=^Build 001", "compose/p-layer-02")
        out, code = self.run_cmd(fc.fc_ship.cmd_reword, set=[f"{sha[:8]}=Add the first thing\n\nIt reads the file."], as_is=False)
        self.assertEqual(code, 0, out)
        self.assertIn("Add the first thing", self.subjects("compose/p-layer-02"))
        self.assertNotIn("Build 001", self.subjects("compose/p-layer-02"))
        for b, tip in tips.items():
            self.assertEqual(self.git("rev-parse", f"{b}^{{tree}}"), self.git("rev-parse", f"{tip}^{{tree}}"))
        self.assertEqual(self.git("rev-parse", "compose/p-layer-01"), tips["compose/p-layer-01"])  # a layer below the change is untouched
        self.assertEqual(self.subjects("compose/p-layer-03")[0], "Build 003")
        self.assertFalse(self.origin_has("refs/heads/compose/p-layer-02"))
        self.assertFalse(any(c.startswith(("pr ", "stack submit", "stack push")) for c in self.log()))
        self.assertTrue(any("nothing pushed" in l for l in out))
        # the choice lives on the commit: any later rebuild applies it again
        self.run_cmd(fc.fc_ship.cmd_stack, submit=False)
        self.assertIn("Add the first thing", self.subjects("compose/p-layer-02"))

    def test_a_message_that_breaks_the_rules_is_refused_unless_taken_as_is(self):
        self.run_cmd(fc.fc_ship.cmd_stack, submit=False)
        sha = self.git("log", "-1", "--format=%H", "--grep=^Build 001", "compose/p-layer-02")
        before = self.git("rev-parse", "compose/p-layer-02")
        out, code = self.run_cmd(fc.fc_ship.cmd_reword, set=[f"{sha[:8]}=Wave 2 of compose run"], as_is=False)
        self.assertEqual(code, 1)
        self.assertTrue(any("mentions the process" in l for l in out))
        self.assertFalse((self.proj / "rewords.json").exists())
        self.assertEqual(self.git("rev-parse", "compose/p-layer-02"), before)
        out, code = self.run_cmd(fc.fc_ship.cmd_reword, set=[f"{sha[:8]}=Wave 2 of compose run"], as_is=True)
        self.assertEqual(code, 0)
        self.assertIn("Wave 2 of compose run", self.git("log", "--format=%s", "main..compose/p-layer-02"))

    def test_a_sha_that_names_no_commit_or_several_is_refused(self):
        self.run_cmd(fc.fc_ship.cmd_stack, submit=False)
        for sha in ("deadbeef", ""):
            out, code = self.run_cmd(fc.fc_ship.cmd_reword, set=[f"{sha}=Add it"], as_is=False)
            self.assertEqual(code, 1)
            self.assertTrue(any("names 0 commits" in l for l in out), out)


class Land(Ship):
    def submitted(self):
        out, code = self.submit()
        self.assertEqual(code, 0, out)
        self.assertEqual(sorted(self.prs()), ["1", "2", "3"])

    def test_without_yes_it_prints_the_plan_and_changes_nothing(self):
        self.submitted()
        refs = lambda: subprocess.run(["git", "--git-dir", str(self.origin), "for-each-ref"], capture_output=True, text=True).stdout
        before, log = refs(), self.log()
        out, code = self.land(yes=False)
        self.assertEqual(code, 0)
        self.assertTrue(any("land   plan  3 layer(s) into main by squash" in l for l in out))
        self.assertTrue(any("nothing was merged or pushed" in l and "--yes" in l for l in out))
        self.assertEqual(refs(), before)
        self.assertEqual([c for c in self.log()[len(log):] if not c.startswith("pr view")], [])

    def test_it_refuses_while_a_verify_holds_the_stack_top_and_merges_nothing(self):
        self.submitted()
        proc = subprocess.Popen(["sleep", "60"]); self.addCleanup(proc.wait); self.addCleanup(proc.kill)
        live = fc.fc_update.live_dir(); live.mkdir(parents=True, exist_ok=True)
        (live / f"{proc.pid}.json").write_text(json.dumps({"pid": proc.pid, "kind": "verify", "project": "p", "repo": str(self.repo), "since": "21:01"}))
        log = self.log()
        with self.assertRaises(SystemExit) as e:
            fc.fc_ship.cmd_land(self.args(yes=True, method=None, timeout=1))
        self.assertIn(f"verify is running on p (pid {proc.pid}", str(e.exception))
        self.assertEqual([c for c in self.log()[len(log):] if not c.startswith("pr view")], [])

    def test_a_stack_that_was_not_submitted_names_the_missing_pull_request(self):
        self.run_cmd(fc.fc_ship.cmd_stack, submit=False)
        out, code = self.land(yes=False)
        self.assertEqual(code, 1)
        self.assertTrue(any("has no pull request" in l and "compose stack --submit" in l for l in out))

    def test_it_merges_bottom_up_waits_for_checks_and_moves_each_next_pr_onto_the_base(self):
        self.submitted()
        self.set_pr(1, checks=["pending", "pending", "pass"])
        self.set_pr(3, checks=["none"])
        out, code = self.land()
        self.assertEqual(code, 0, out)
        prs = self.prs()
        self.assertEqual([p["state"] for p in prs.values()], ["MERGED"] * 3)
        self.assertEqual([p["base"] for p in prs.values()], ["main"] * 3)
        log = self.log()
        merges = [c for c in log if c.startswith("pr merge")]
        self.assertEqual(merges, ["pr merge 1 --squash", "pr merge 2 --squash", "pr merge 3 --squash"])
        self.assertEqual([c for c in log if c.startswith("pr ready")], ["pr ready 1", "pr ready 2", "pr ready 3"])
        self.assertLess(log.index("pr merge 1 --squash"), log.index("pr edit 2 --base main"))
        self.assertLess(log.index("pr edit 2 --base main"), log.index("pr merge 2 --squash"))
        self.assertLess(log.index("pr merge 2 --squash"), log.index("pr edit 3 --base main"))
        self.assertGreaterEqual(len([c for c in log if c.startswith("pr checks 1")]), 3)
        top = subprocess.run(["git", "--git-dir", str(self.origin), "ls-tree", "-r", "--name-only", "main"], capture_output=True, text=True).stdout.split()
        self.assertEqual(sorted(top), ["001.src", "002.src", "003.src", "README.md", "setup.txt", "t001.test", "t002.test", "t003.test"])
        self.assertEqual(out[-1], "next: compose clean --project p")
        self.assertFalse((self.proj / "results" / "land.json").exists())
        self.assertEqual(self.git("branch", "--show-current"), "compose/p")  # the user's checkout never moved

    def test_a_failing_check_on_the_first_pr_stops_before_anything_is_merged_or_moved(self):
        self.submitted()
        pushed_before = self.git("rev-parse", "compose/p-layer-03")
        self.set_pr(1, checks=["fail"])
        out, code = self.land()
        self.assertEqual(code, 1)
        self.assertTrue(any("required checks on #1 (compose/p-layer-01): fail: ci" in l for l in out))
        self.assertEqual(self.prs()["1"]["state"], "OPEN")
        self.assertFalse(any(c.startswith("pr merge") for c in self.log()))
        self.assertEqual(self.git("rev-parse", "compose/p-layer-03"), pushed_before)

    def test_a_failing_check_stops_the_land_and_a_rerun_resumes_where_it_stopped(self):
        self.submitted()
        self.set_pr(2, checks=["fail"])
        out, code = self.land()
        self.assertEqual(code, 1)
        self.assertEqual([p["state"] for p in self.prs().values()], ["MERGED", "OPEN", "OPEN"])
        self.assertTrue(any("required checks on #2" in l and "re-run `compose land` to resume" in l for l in out))
        self.assertEqual(self.prs()["2"]["base"], "main")  # moved onto the base before its checks were read
        self.assertTrue((self.proj / "results" / "land.json").exists())
        self.set_pr(2, checks=["pass"])
        merges = len([c for c in self.log() if c.startswith("pr merge")])
        out, code = self.land()
        self.assertEqual(code, 0, out)
        self.assertEqual([p["state"] for p in self.prs().values()], ["MERGED"] * 3)
        self.assertEqual(len([c for c in self.log() if c.startswith("pr merge")]), merges + 2)  # PR 1 is not merged twice
        self.assertTrue(any("#1" in l and "already merged" in l for l in out))

    def test_checks_that_stay_pending_stop_it_at_the_timeout(self):
        self.submitted()
        self.set_pr(1, checks=["pending"])
        out, code = self.land(timeout=0)
        self.assertEqual(code, 1)
        self.assertTrue(any("still pending after 0 minutes" in l for l in out))
        self.assertEqual(self.prs()["1"]["state"], "OPEN")

    def test_a_refused_merge_stops_with_what_github_said(self):
        self.submitted()
        self.set_pr(1, refuse="Pull request is not mergeable: the base branch policy prohibits the merge")
        out, code = self.land()
        self.assertEqual(code, 1)
        self.assertTrue(any("gh pr merge #1" in l and "base branch policy prohibits" in l for l in out))

    def test_a_pr_whose_head_is_not_what_was_submitted_is_not_merged(self):
        self.submitted()
        self.git("checkout", "-q", "compose/p-layer-01")
        self.write("extra.txt", "x\n"); self.commit("Local change")
        self.git("checkout", "-q", "compose/p")
        out, code = self.land()
        self.assertEqual(code, 1)
        self.assertTrue(any("has commits compose did not push" in l or "submit" in l for l in out))
        self.assertFalse(any(c.startswith("pr merge") for c in self.log()))

    def test_a_next_layer_that_conflicts_with_the_base_stops_with_the_files_and_pushes_nothing(self):
        self.submitted()
        self.set_pr(1, extra=["002.src", "from the base\n"])
        top = self.git("rev-parse", "compose/p-layer-02")
        out, code = self.land()
        self.assertEqual(code, 1)
        self.assertEqual(self.prs()["1"]["state"], "MERGED")
        self.assertTrue(any("compose/p-layer-02 conflicts with main in 002.src" in l and "nothing of it was pushed" in l for l in out), out)
        self.assertEqual(self.git("rev-parse", "compose/p-layer-02"), top)
        self.assertEqual(self.prs()["2"]["state"], "OPEN")
        self.assertEqual(self.prs()["2"]["base"], "compose/p-layer-01")
        self.assertEqual(self.git("-C", str(fc.fc_worktree.stack_worktree(self.repo, self.proj, "compose/p")), "status", "--porcelain"), "")  # no rebase left half done

    def test_a_pr_behind_the_base_is_updated_before_it_merges(self):
        self.submitted()
        self.set_pr(1, behind=True)
        out, code = self.land()
        self.assertEqual(code, 0, out)
        self.assertIn("pr update-branch 1 --rebase", self.log())
        self.assertEqual([p["state"] for p in self.prs().values()], ["MERGED"] * 3)

    def test_the_merge_method_follows_the_flag_then_verify_json(self):
        self.submitted()
        self.config(land_method="rebase")
        self.land()
        self.assertEqual([c for c in self.log() if c.startswith("pr merge")][0], "pr merge 1 --rebase")


class PartialSubmit(Ship):
    def result(self, tid, status):
        (self.proj / "results" / f"{tid}.json").write_text(json.dumps({"status": status}))

    def origin_git(self, *a):
        return subprocess.run(["git", "--git-dir", str(self.origin), *a], check=True, capture_output=True, text=True).stdout.split()

    def pushed(self):
        """Origin's layer refs and SHAs, and every file in any ref but main."""
        refs = {r.removeprefix("refs/heads/"): s for s, r in zip(*[iter(self.origin_git("for-each-ref", "--format=%(objectname) %(refname)", "refs/heads/compose"))] * 2)}
        return refs, {f for r in refs for f in self.origin_git("ls-tree", "-r", "--name-only", r)}

    def test_a_failed_task_holds_it_and_the_ones_after_back_and_a_later_submit_adds_them(self):
        self.result("002", "failed")
        out, code = self.submit()
        self.assertEqual(code, 0, out)
        self.assertTrue(any("stack  hold  002 is failed; 002, 003 not submitted" in l for l in out), out)
        before, files = self.pushed()
        self.assertTrue({"setup.txt", "001.src", "t001.test"} <= files)
        self.assertFalse(files & {"002.src", "003.src", "t002.test", "t003.test"})
        self.assertEqual(set(json.loads((self.proj / "results" / "prs.json").read_text())), set(before))
        self.result("002", "passed")
        out, code = self.submit()
        self.assertEqual(code, 0, out)
        after, files = self.pushed()
        self.assertTrue({"002.src", "003.src", "t002.test", "t003.test"} <= files)
        self.assertEqual({b: after[b] for b in before}, before)
        self.assertEqual(json.loads((self.proj / "results" / "prs.json").read_text()), {p["branch"]: int(n) for n, p in self.prs().items()})

    def test_every_task_done_pushes_every_layer_and_maps_each_to_its_pr(self):
        out, code = self.submit()
        self.assertEqual(code, 0, out)
        self.assertFalse(any("stack  hold" in l for l in out))
        self.assertEqual(json.loads((self.proj / "results" / "prs.json").read_text()), {f"compose/p-layer-0{i}": i for i in (1, 2, 3)})

    def test_a_task_done_on_linear_is_not_held_whatever_its_result(self):
        self.result("002", "failed")
        tasks = json.loads((self.proj / "results" / "tasks.json").read_text())
        tasks["tasks"][1]["linear_state"] = "Done"
        (self.proj / "results" / "tasks.json").write_text(json.dumps(tasks))
        out, code = self.submit()
        self.assertEqual(code, 0, out)
        self.assertTrue({"002.src", "003.src"} <= self.pushed()[1])
        self.assertTrue((self.proj / "results" / "prs.json").exists())

    def test_a_pending_first_task_stops_with_nothing_pushed(self):
        (self.proj / "results" / "001.json").unlink()
        out, code = self.submit()
        self.assertEqual(code, 1)
        self.assertTrue(any("stack  STOP  nothing to submit: 001 is pending" in l for l in out), out)
        self.assertEqual(self.pushed()[0], {})
        self.assertFalse(any("stack submit" in c for c in self.log()))


class ChangedLayer(Ship):
    LAYERS = [f"compose/p-layer-0{i}" for i in (1, 2, 3)]

    def heads(self, local=False):
        git = (lambda *a: self.git(*a)) if local else (lambda *a: self.git("--git-dir", str(self.origin), *a))
        return [git("rev-parse", b if local else f"refs/heads/{b}") for b in self.LAYERS]

    def stop_line(self, i, before, cause):
        b, tip = self.LAYERS[i - 1], self.heads(local=True)[i - 1]
        return (f"stack  STOP  layer {i} ({b}) changed since PR #{i}: GitHub has {before[i - 1][:9]}, here {tip[:9]}; {cause}. Nothing was pushed. "
                "`compose stack --submit --update` pushes it with --force-with-lease")

    def change_001(self):
        self.assertEqual(self.submit()[1], 0)
        self.git("checkout", "-q", "compose/p-001"); self.write("001.src", "d\n"); self.commit("Change 001"); self.git("checkout", "-q", "compose/p")
        return self.heads()

    def test_an_unchanged_stack_pushes_as_before(self):
        self.submit()
        before = self.heads()
        out, code = self.submit()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.heads(), before)

    def test_a_layer_whose_own_file_changed_stops_the_submit_with_nothing_pushed(self):
        before = self.change_001()
        out, code = self.submit()
        self.assertEqual(code, 1)
        self.assertIn(self.stop_line(2, before, "its own files changed: 001.src"), out)
        self.assertEqual(self.heads(), before)

    def test_a_layer_that_moved_with_the_base_is_named_as_such(self):
        self.submit()
        before = self.heads()
        self.git("checkout", "-q", "main"); self.write("base.txt", "b\n"); self.commit("Move the base"); self.git("push", "-q", "origin", "main"); self.git("checkout", "-q", "compose/p")
        out, code = self.submit()
        self.assertEqual(code, 1)
        self.assertIn(self.stop_line(1, before, "a layer below it or the base moved"), out)
        self.assertEqual(self.heads(), before)

    def test_update_pushes_each_changed_layer_bottom_up_and_opens_no_pull_request(self):
        before = self.change_001()
        out, code = self.run_cmd(fc.fc_ship.cmd_stack, submit=True, update=True)
        self.assertEqual(code, 0, out)
        tips = self.heads(local=True)
        self.assertEqual(self.heads(), tips)
        lines = [f"submit update {b} {tips[i][:9]} (was {before[i][:9]})" for i, b in enumerate(self.LAYERS) if i]
        at = [next(n for n, l in enumerate(out) if want in l) for want in lines]
        self.assertEqual(at, sorted(at))
        self.assertEqual(len(self.prs()), 3)
        out, code = self.submit()
        self.assertEqual(code, 0, out)

    def test_a_layer_whose_pull_request_is_not_open_is_not_compared(self):
        before = self.change_001()
        self.set_pr(2, state="CLOSED")
        out, code = self.submit()
        self.assertEqual(code, 1)
        self.assertIn(self.stop_line(3, before, "a layer below it or the base moved"), out)

    def test_a_refused_push_is_the_reason_and_pushes_nothing_after_it(self):
        before = self.change_001()
        hook = self.origin / "hooks" / "pre-receive"
        hook.write_text("#!/bin/sh\necho nope >&2\nexit 1\n"); hook.chmod(0o755)
        out, code = self.run_cmd(fc.fc_ship.cmd_stack, submit=True, update=True)
        self.assertEqual(code, 1)
        self.assertTrue(any("stack  STOP  push of compose/p-layer-02 refused: " in l for l in out), out)
        self.assertEqual(self.heads(), before)


class PartialLand(Ship):
    def partial(self):
        """Submitted, then layer 3 loses its PR and its branch on origin."""
        self.assertEqual(self.submit()[1], 0)
        self.drop_pr(3)
        subprocess.run(["git", "--git-dir", str(self.origin), "update-ref", "-d", "refs/heads/compose/p-layer-03"], check=True)

    def drop_pr(self, n):
        st = json.loads(self.state.read_text()); del st["prs"][str(n)]; self.state.write_text(json.dumps(st))

    def test_the_plan_lists_only_the_submitted_layers(self):
        self.partial()
        out, code = self.land(yes=False)
        self.assertEqual(code, 0, out)
        self.assertIn("land   plan  2 of 3 layer(s) submitted, verify not run; landing 2 into main by squash, bottom up:", out)
        self.assertTrue(any("compose/p-layer-02" in l for l in out))
        self.assertFalse(any("compose/p-layer-03" in l for l in out))
        self.assertFalse(any(c.startswith("pr merge") for c in self.log()))

    def test_yes_merges_the_submitted_layers_bottom_up_and_leaves_the_rest(self):
        self.partial()
        out, code = self.land()
        self.assertEqual(code, 0, out)
        self.assertEqual([c for c in self.log() if c.startswith("pr merge")], ["pr merge 1 --squash", "pr merge 2 --squash"])
        self.assertFalse(self.origin_has("refs/heads/compose/p-layer-03"))
        self.assertEqual(out[-3:], ["land   done  2 layer(s) merged into main",
                                    "land   left  1 layer(s) not submitted: they rebuild on main at the next compose stack",
                                    "next: compose stack --submit --project p"])

    def test_the_plan_reports_the_last_verify(self):
        self.submit()
        for passed, word in ((True, "PASS"), (False, "FAIL")):
            (self.proj / "results" / "verify.json").write_text(json.dumps({"passed": passed}))
            out, _ = self.land(yes=False)
            self.assertIn(f"land   plan  3 of 3 layer(s) submitted, verify {word}; landing 3 into main by squash, bottom up:", out)

    def test_a_fully_submitted_stack_lands_as_today(self):
        self.submit()
        out, code = self.land()
        self.assertEqual(code, 0, out)
        self.assertEqual(out[-2:], ["land   done  3 layer(s) merged into main", "next: compose clean --project p"])
        self.assertFalse(any("land   left" in l for l in out))

    def test_a_bottom_layer_without_a_pull_request_stops(self):
        self.submit()
        self.drop_pr(1)
        out, code = self.land()
        self.assertEqual(code, 1)
        self.assertTrue(any(l.startswith("land   STOP  compose/p-layer-01") and l.endswith("has no pull request: `compose stack --submit` first") for l in out), out)
        self.assertFalse(any(c.startswith("pr merge") for c in self.log()))


class LandedLayers(Ship):
    def merge(self, n):
        subprocess.run(["gh", "pr", "edit", str(n), "--base", "main"], cwd=self.repo, check=True)
        subprocess.run(["gh", "pr", "merge", str(n), "--squash"], cwd=self.repo, check=True)

    def tree(self, ref):
        return self.git("ls-tree", "-r", "--name-only", ref).splitlines()

    def assert_built_on_main(self, branch, file, below="main"):
        self.assertIn(file, self.tree(branch))
        self.assertTrue(self.git("rev-list", f"{below}..{branch}"), f"{branch} adds nothing over {below}")
        self.assertEqual(subprocess.run(["git", "merge-base", "--is-ancestor", "main", branch], cwd=self.repo).returncode, 0)

    def test_the_layers_above_a_merged_bottom_build_on_the_new_base(self):
        self.submit(); self.merge(1)
        out, code = self.run_cmd(fc.fc_ship.cmd_stack, submit=False)
        self.assertEqual(code, 0, out)
        self.assertIn("stack  landed compose/p-layer-01; building on origin/main", out)
        self.assertFalse(any("STOP" in l for l in out), out)
        self.assertEqual(self.git("rev-parse", "main"), self.git("--git-dir", str(self.origin), "rev-parse", "main"))
        self.assert_built_on_main("compose/p-layer-02", "002.src")
        self.assert_built_on_main("compose/p-layer-03", "003.src", "compose/p-layer-02")

    def test_two_merged_layers_are_both_named_and_the_last_one_builds_on_the_base(self):
        self.submit(); self.merge(1); self.merge(2)
        out, code = self.run_cmd(fc.fc_ship.cmd_stack, submit=False)
        self.assertEqual(code, 0, out)
        self.assertIn("stack  landed compose/p-layer-01, compose/p-layer-02; building on origin/main", out)
        self.assert_built_on_main("compose/p-layer-03", "003.src")

    def test_open_pull_requests_or_no_layers_file_fetch_nothing(self):
        self.submit()
        old = self.git("rev-parse", "main")
        self.git("checkout", "-q", "main"); self.write("base.txt", "b\n"); self.commit("Move the base"); self.git("push", "-q", "origin", "main")
        self.git("checkout", "-q", "compose/p"); self.git("branch", "-f", "main", old)
        for _ in range(2):
            out, code = self.run_cmd(fc.fc_ship.cmd_stack, submit=False)
            self.assertFalse(any("landed" in l for l in out), out)
            self.assertEqual(self.git("rev-parse", "main"), old)
            (self.proj / "layers.json").unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
