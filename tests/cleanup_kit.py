import hermetic  # first: no test sees the real home
import importlib.machinery, importlib.util, os, subprocess, sys, tempfile
from pathlib import Path
os.environ["COMPOSE_NO_TREEHOUSE"] = "1"  # these cover the plain-worktree path; test_treehouse covers the pool
os.environ["HERDR_ENV"] = ""

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)

CLI = str(Path(__file__).resolve().parents[1] / "bin" / "compose")

ENV = {"COMPOSE_NO_TRAIL": "1", "HERDR_ENV": "", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}

def repo():
    r = Path(tempfile.mkdtemp()).resolve() / "repo"
    r.mkdir()
    run = lambda *a, cwd=r: subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True)
    run("init", "-q", "-b", "main")
    (r / "a.txt").write_text("base\n")
    (r / ".git" / "info" / "exclude").write_text("/.compose/\n")
    run("add", "-A"); run("commit", "-qm", "init")
    return r, run


class FakeLinear:
    """Linear in memory: issues by identifier, each with a state and a parent. A state's id is its name."""
    TYPES = {"Todo": "unstarted", "In Progress": "started", "In Review": "started", "Done": "completed", "Canceled": "canceled"}

    def __init__(self, **issues):
        self.issues = {k.replace("_", "-"): {"state": s, "parent": p} for k, (s, p) in issues.items()}

    def __call__(self, query, variables):
        if "issueUpdate" in query:
            self.issues[variables["id"]]["state"] = variables["s"]
            return {"issueUpdate": {"success": True}}
        ident, d = variables["id"], self.issues[variables["id"]]
        st = lambda n: {"name": n, "type": self.TYPES[n]}
        return {"issue": {"id": ident, "identifier": ident, "state": st(d["state"]),
                          "team": {"states": {"nodes": [{"id": n, "name": n, "type": t} for n, t in self.TYPES.items()]}},
                          "parent": {"identifier": d["parent"]} if d["parent"] else None,
                          "children": {"nodes": [{"identifier": c, "state": st(cd["state"])} for c, cd in self.issues.items() if cd["parent"] == ident]}}}

    def states(self, *idents):
        return [self.issues[i]["state"] for i in idents]
