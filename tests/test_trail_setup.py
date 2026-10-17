import importlib.machinery, importlib.util, json, os, stat, subprocess, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
import shutil, sys
os.environ["COMPOSE_NO_TREEHOUSE"] = "1"  # these cover the plain-worktree path; test_treehouse covers the pool

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)

ENV = {"HERDR_ENV": "", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}

# A stand-in graft: logs every call, lists what init would write, and writes it (or the graph) like the real one.
FAKE_GRAFT = """#!/bin/sh
echo "$*" >> "$GRAFT_LOG"
case "$1 $2" in
  "--version "*) echo 9.9.9;;
  "init --no-agents")
    case "$*" in *--dry-run*)
      printf 'would write \\342\\200\\224 this repo:\\n  .claude/settings.json   graft statusline\\n  .claude/helpers/graft-hooks.cjs   hooks shim\\n  .mcp.json   mcpServers.graft\\n\\nnothing was written (--dry-run)\\n' >&2
      exit 0;; esac
    d="${@: -1}"; mkdir -p "$d/.claude/helpers"; echo x > "$d/.claude/helpers/graft-hooks.cjs"; echo '{}' > "$d/.claude/settings.json"; echo '{}' > "$d/.mcp.json";;
  "build --no-gitignore") d="${@: -1}"; g="$d/graft"  # graft 0.23 keeps the graph in .trail/cache once the repo is on trail
    if [ -d "$d/.trail/cache" ] || [ -d "$d/.trail/learnings" ]; then g="$d/.trail/cache"; fi
    mkdir -p "$g"; echo index > "$g/INDEX.md";;
  "ask "*) d="${@: -1}"; [ -f "$d/graft/INDEX.md" ] || [ -f "$d/.trail/cache/INDEX.md" ] || exit 1
    printf '[graft] tokens saved ≈ 7,434 (95%%) — this pack ≈ 384 tok vs reading the 1 source file(s) whole ≈ 7,818 tok.\n\n'
    printf 'graft ask — "%s"  (lexical)\n\n' "$2"
    if [ "$2" = main ]; then cat <<'OUT'
from Reggie's learning · Oct 17 · Use @trailhq/trail-code and call `trail`, not `graft`
  decided     graft's npm package was renamed to `@trailhq/trail-code`.
  .trail/learnings/2026-10-17-use-trailhq-trail-code.md

[trail] starting from this learning gets you to a PR 3x faster.

OUT
    else printf '· no learnings about this yet\n\n'; fi
    printf '1. main · function  [symbol]\n   server/main.go:L1-L1\n';;
esac
"""
# A stand-in trail: logs every call, lists what init would write and writes it, and builds the map where trail 0.23 would.
FAKE_TRAIL = r"""#!/bin/bash
echo "$*" >> "$TRAIL_LOG"
d="${@: -1}"
case "$1 $2" in
  "--version "*) echo 9.9.9;;
  "init --no-agents")
    case "$*" in *--dry-run*)
      printf 'would write \342\200\224 this repo:\n  .claude/settings.json        trail SessionStart hook, shared\n  .trail/hook.cjs              hooks shim, shared\n  .claude/settings.local.json  trail statusline + allowlist, yours\n  .trail/statusline.cjs        statusline shim, git-ignored\n\nwould write \342\200\224 your machine, affects ALL repos:\n  ~/.claude/skills/trail/SKILL.md    trail skill\n\nnothing was written (--dry-run)\n' >&2
      exit 0;; esac
    mkdir -p "$d/.claude" "$d/.trail/learnings"; echo x > "$d/.trail/hook.cjs"; echo x > "$d/.trail/statusline.cjs"
    echo statusline.cjs > "$d/.trail/.gitignore"; echo '{}' > "$d/.claude/settings.json"; echo '{}' > "$d/.claude/settings.local.json";;
  "build --no-gitignore") g="$d/graft"
    if [ -d "$d/.trail/cache" ] || [ -d "$d/.trail/learnings" ] || [ -f "$d/.trail/hook.cjs" ]; then g="$d/.trail/cache"; fi
    mkdir -p "$g"; echo index > "$g/INDEX.md";;
  "ask "*) [ -f "$d/graft/INDEX.md" ] || [ -f "$d/.trail/cache/INDEX.md" ] || exit 1
    printf '[trail] tokens saved ≈ 7,434 (95%%) — this pack ≈ 384 tok vs reading the 1 source file(s) whole ≈ 7,818 tok.\n\n'
    printf 'trail ask — "%s"  (lexical)\n\n' "$2"
    if [ "$2" = main ]; then cat <<'OUT'
from Reggie's learning · Oct 17 · Use @trailhq/trail-code and call `trail`, not `graft`
  decided     graft's npm package was renamed to `@trailhq/trail-code`.
  .trail/learnings/2026-10-17-use-trailhq-trail-code.md

[trail] starting from this learning gets you to a PR 3x faster.

OUT
    else printf '· no learnings about this yet\n\n'; fi
    printf '1. main · function  [symbol]\n   server/main.go:L1-L1\n';;
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


class FakeGraft(unittest.TestCase):
    def setUp(self):
        bindir = Path(tempfile.mkdtemp())
        (bindir / "graft").write_text(FAKE_GRAFT.replace("#!/bin/sh", "#!/bin/bash"))
        (bindir / "graft").chmod(stat.S_IRWXU)
        self.log = bindir / "calls.log"
        env = {**ENV, "PATH": f"{bindir}:{os.environ['PATH']}", "GRAFT_LOG": str(self.log)}
        self.env = mock.patch.dict(os.environ, env); self.env.start(); self.addCleanup(self.env.stop)

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []


class FakeTrail(unittest.TestCase):
    def setUp(self):
        bindir = Path(tempfile.mkdtemp())
        (bindir / "trail").write_text(FAKE_TRAIL)
        (bindir / "trail").chmod(stat.S_IRWXU)
        self.log = bindir / "calls.log"
        env = {**ENV, "PATH": f"{bindir}:{os.environ['PATH']}", "TRAIL_LOG": str(self.log)}
        self.env = mock.patch.dict(os.environ, env); self.env.start(); self.addCleanup(self.env.stop)

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []


class GraftSetup(FakeGraft):
    """An existing repo gets graft wired and built before anyone explores it; graft's files never reach git."""

    def test_existing_repo_is_wired_built_and_kept_out_of_git(self):
        repo, run = repo_with({"server/main.go": "package main\n", "README.md": "x"})
        fc.fc_init.setup_graft(repo)
        self.assertTrue((repo / "graft" / "INDEX.md").exists())
        self.assertEqual(run("status", "--porcelain").stdout.strip(), "")  # wiring and graph are excluded, nothing shows up
        n = len(self.calls())
        fc.fc_init.setup_graft(repo)  # again: already wired, so only a rebuild
        self.assertEqual([c.split()[0] for c in self.calls()[n:]], ["build"])

    def test_a_tracked_file_init_would_edit_means_build_only(self):
        repo, _ = repo_with({"server/main.go": "package main\n", ".mcp.json": "{\"mine\": true}"})
        fc.fc_init.setup_graft(repo)
        self.assertFalse(any(c.startswith("init") and "--dry-run" not in c for c in self.calls()))
        self.assertEqual(json.loads((repo / ".mcp.json").read_text()), {"mine": True})
        self.assertTrue((repo / "graft" / "INDEX.md").exists())

    def test_tracked_wiring_gets_a_stamp_so_graft_never_refreshes_it(self):
        # graft's session-start hook rewrites wired files when graft/.cache/wiring-stamp.json is missing or older than graft
        repo, _ = repo_with({"server/main.go": "package main\n", ".claude/helpers/graft-hooks.cjs": "x"})
        stamp = repo / "graft" / ".cache" / "wiring-stamp.json"
        fc.fc_init.setup_graft(repo)
        self.assertEqual(json.loads(stamp.read_text())["version"], "9.9.9")
        clone = Path(tempfile.mkdtemp()) / "clone"
        subprocess.run(["git", "clone", "-q", str(repo), str(clone)], check=True)
        fc.fc_worktree.ready_checkout(repo, clone)  # a task clone or verify worktree starts without graft/ at all
        self.assertEqual(json.loads((clone / "graft" / ".cache" / "wiring-stamp.json").read_text())["version"], "9.9.9")

    def test_a_repo_on_trail_gets_its_graph_in_trail_cache_kept_out_of_git(self):
        repo, run = repo_with({"server/main.go": "package main\n", ".gitignore": "node_modules/\n"})
        (repo / ".trail" / "learnings").mkdir(parents=True)  # what trail's session-start hook leaves behind
        (repo / ".trail" / "hook.cjs").write_text("x")
        fc.fc_init.setup_graft(repo)
        self.assertTrue((repo / ".trail" / "cache" / "INDEX.md").exists())
        self.assertFalse((repo / "graft").exists())
        self.assertEqual(run("status", "--porcelain").stdout.strip(), "")
        self.assertTrue(fc.fc_worktree.ignore_tool_files(repo))  # a clone of the delivered branch ignores it too
        self.assertIn(".trail/", (repo / ".gitignore").read_text().splitlines())

    def test_a_new_repo_skips_graft(self):
        repo, _ = repo_with({"README.md": "x", "LICENSE": "x"})
        fc.fc_init.setup_graft(repo)
        self.assertEqual(self.calls(), [])

    def test_missing_graft_says_how_to_install(self):
        repo, _ = repo_with({"main.go": "package main\n"})
        with mock.patch.object(shutil, "which", return_value=None), mock.patch.object(fc.fc_core, "say") as say:
            fc.fc_init.setup_graft(repo)
        self.assertIn("npm i -g @nanonets/graft", say.call_args[0][0])
        self.assertEqual(self.calls(), [])


if __name__ == "__main__":
    unittest.main()
