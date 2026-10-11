import importlib.machinery, importlib.util, json, os, stat, subprocess, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
os.environ["FAST_CODING_NO_TREEHOUSE"] = "1"  # these cover the plain-worktree path; test_treehouse covers the pool

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "fast-coding")))
fc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fc)

ENV = {"HERDR_ENV": "", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}

# A stand-in graft: logs every call, lists what init would write, and writes it (or the graph) like the real one.
FAKE_GRAFT = """#!/bin/sh
echo "$*" >> "$GRAFT_LOG"
case "$1 $2" in
  "init --no-agents")
    case "$*" in *--dry-run*)
      printf 'would write \\342\\200\\224 this repo:\\n  .claude/settings.json   graft statusline\\n  .claude/helpers/graft-hooks.cjs   hooks shim\\n  .mcp.json   mcpServers.graft\\n\\nnothing was written (--dry-run)\\n' >&2
      exit 0;; esac
    d="${@: -1}"; mkdir -p "$d/.claude/helpers"; echo x > "$d/.claude/helpers/graft-hooks.cjs"; echo '{}' > "$d/.claude/settings.json"; echo '{}' > "$d/.mcp.json";;
  "build --no-gitignore") d="${@: -1}"; mkdir -p "$d/graft"; echo index > "$d/graft/INDEX.md";;
esac
"""


def repo_with(files):
    r = Path(tempfile.mkdtemp())
    run = lambda *a: subprocess.run(["git", *a], cwd=r, check=True, capture_output=True, text=True)
    run("init", "-q", "-b", "main")
    for name, text in files.items():
        (r / name).parent.mkdir(parents=True, exist_ok=True)
        (r / name).write_text(text)
    run("add", "-A"); run("commit", "-qm", "init")
    return r, run


class GraftSetup(unittest.TestCase):
    """An existing repo gets graft wired and built before anyone explores it; graft's files never reach git."""
    def setUp(self):
        bindir = Path(tempfile.mkdtemp())
        (bindir / "graft").write_text(FAKE_GRAFT.replace("#!/bin/sh", "#!/bin/bash"))
        (bindir / "graft").chmod(stat.S_IRWXU)
        self.log = bindir / "calls.log"
        env = {**ENV, "PATH": f"{bindir}:{os.environ['PATH']}", "GRAFT_LOG": str(self.log)}
        self.env = mock.patch.dict(os.environ, env); self.env.start(); self.addCleanup(self.env.stop)

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def test_existing_repo_is_wired_built_and_kept_out_of_git(self):
        repo, run = repo_with({"server/main.go": "package main\n", "README.md": "x"})
        fc.setup_graft(repo)
        self.assertTrue((repo / "graft" / "INDEX.md").exists())
        self.assertEqual(run("status", "--porcelain").stdout.strip(), "")  # wiring and graph are excluded, nothing shows up
        n = len(self.calls())
        fc.setup_graft(repo)  # again: already wired, so only a rebuild
        self.assertEqual([c.split()[0] for c in self.calls()[n:]], ["build"])

    def test_a_tracked_file_init_would_edit_means_build_only(self):
        repo, _ = repo_with({"server/main.go": "package main\n", ".mcp.json": "{\"mine\": true}"})
        fc.setup_graft(repo)
        self.assertFalse(any(c.startswith("init") and "--dry-run" not in c for c in self.calls()))
        self.assertEqual(json.loads((repo / ".mcp.json").read_text()), {"mine": True})
        self.assertTrue((repo / "graft" / "INDEX.md").exists())

    def test_a_new_repo_skips_graft(self):
        repo, _ = repo_with({"README.md": "x", "LICENSE": "x"})
        fc.setup_graft(repo)
        self.assertEqual(self.calls(), [])

    def test_missing_graft_says_how_to_install(self):
        repo, _ = repo_with({"main.go": "package main\n"})
        with mock.patch.object(fc.shutil, "which", return_value=None), mock.patch.object(fc, "say") as say:
            fc.setup_graft(repo)
        self.assertIn("npm i -g @nanonets/graft", say.call_args[0][0])
        self.assertEqual(self.calls(), [])


class Explore(unittest.TestCase):
    def test_brief_is_graft_only_time_boxed_and_names_the_feature(self):
        proj = Path(tempfile.mkdtemp()) / ".fast-coding" / "p"
        proj.mkdir(parents=True)
        (proj / "linear.json").write_text(json.dumps({"feature": "ENG-7"}))
        out = []
        with mock.patch.object(fc, "project_dir", return_value=proj), mock.patch.object(fc, "project_worktree", return_value=proj.parent.parent), \
                mock.patch("builtins.print", side_effect=lambda s: out.append(s)):
            fc.cmd_explore(SimpleNamespace(extra="the client lives in web/"))
        brief = out[0]
        for want in ("ENG-7", "graft ask", "graft callers", "under 3 minutes", "at most 40 lines", "patch append", "the client lives in web/"):
            self.assertIn(want, brief)


if __name__ == "__main__":
    unittest.main()
