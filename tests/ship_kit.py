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
                st["prs"][str(len(st["prs"]) + 1)] = {"branch": b["name"], "base": below, "state": "OPEN", "draft": True, "stacked": False, "checks": ["pass"], "title": "t", "body": "b"}
            below = b["name"]
    else:
        done(1)
    done()
def merge(n, p):
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
    for q in st["prs"].values():  # a stack: GitHub moves the layer above onto the base and rewrites its head
        if q["stacked"] and q["base"] == p["branch"]:
            q["base"] = p["base"]
            ogit("update-ref", "refs/heads/" + q["branch"], ogit("commit-tree", head(q) + "^{tree}", "-p", ogit("rev-parse", "refs/heads/" + p["base"]), "-m", "rebased by GitHub"))
if a[0] == "api":  # the stack field of a PR, and the asynchronous merge of a PR in a stack
    path = next((x for x in a if "/pulls/" in x), "")
    n, p = find(path.split("/pulls/")[1].split("/")[0] if path else next(x.split("=")[1] for x in a if x.startswith("n=")))
    if "graphql" in a:
        print(json.dumps({"data": {"repository": {"pullRequest": {"stack": {"size": 3} if p.get("stacked") else None}}}})); done()
    if "PUT" in a:
        if p["draft"]:
            print("Pull request is in draft", file=sys.stderr); done(1)
        sha = next(x.split("=", 1)[1] for x in a if x.startswith("sha="))
        p["async"] = {"uuid": "u" + n, "method": next(x.split("=", 1)[1] for x in a if x.startswith("merge_method=")), "sha": sha, "polls": 0}
        print(json.dumps({"status": "pending", "details": {"uuid": "u" + n}})); done()
    p["async"]["polls"] += 1
    if p["async"]["polls"] < 2:
        print(json.dumps({"status": "pending", "details": {"uuid": "u" + n}})); done()
    if p.get("refuse") or p["async"]["sha"] != head(p):
        print(json.dumps({"status": "failed", "details": {"message": p.get("refuse") or "head changed"}})); done()
    merge(n, p)
    print(json.dumps({"status": "merged", "details": {"message": "ok", "sha": "abc"}})); done()
n, p = find(a[2]) if len(a) > 2 else (None, None)
if a[:2] == ["pr", "view"]:
    if os.environ.get("FAKE_GH_VIEW_FAIL"):
        print(os.environ["FAKE_GH_VIEW_FAIL"], file=sys.stderr); done(1)
    if not p:
        print('no pull requests found for branch "' + a[2] + '"', file=sys.stderr); done(1)
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
    if p.get("stacked"):
        print("GraphQL: This pull request is part of a stack and must be merged using the asynchronous merge REST API (mergePullRequest)", file=sys.stderr); done(1)
    if p.get("refuse"):
        print(p["refuse"], file=sys.stderr); done(1)
    merge(n, p)
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
        tasks = [{"id": t, "protected": [f"t{t}.test"], "files": [f"{t}.src"], "after": "", "test": f"test -f {t}.src", "title": f"Build {t}", "linear": f"ENG-{t}", "body": f"## Goal\nBuild {t}.\n"}
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
