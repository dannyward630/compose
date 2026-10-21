import hermetic  # first: no test sees the real home
import json, os, pwd, shutil, subprocess, sys, tempfile, time, unittest
from pathlib import Path
os.environ["HERDR_ENV"] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_setup_e2e import RECORD, TOOLS, SetupE2E
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import fc_harness

ROOT = Path(__file__).resolve().parents[1]
CODEX = shutil.which("codex")
# The account's Codex home holds its sign-in; a scratch one would lose it, and the sign-in is never copied or linked.
SIGNED_IN = Path(os.environ.get("CODEX_HOME") or Path(pwd.getpwuid(os.getuid()).pw_dir) / ".codex")


@unittest.skipUnless(CODEX, "codex is not installed")
class CodexCommandsE2E(SetupE2E, unittest.TestCase):
    """The real codex binary runs a compose command copy that `compose setup` wrote in a scratch home."""

    def test_words_after_the_skill_name_reach_the_shell_line(self):
        r = self.run_setup("--yes", tools={**{t: RECORD for t in TOOLS}, "codex": RECORD}, CODEX_HOME="")
        copy = r.home / ".codex/skills/compose-workspace"
        self.assertTrue((copy / "SKILL.md").is_file(), "\n".join(r.lines))
        # Codex reads the account's own skills folder under SIGNED_IN, so it sees setup's copy through ~/.agents/skills
        (r.home / ".agents/skills").mkdir(parents=True)
        (r.home / ".agents/skills/compose-workspace").symlink_to(copy)
        env = {k: v for k, v in os.environ.items() if not k.startswith("HERDR_")} | {
            "HOME": str(r.home), "CODEX_HOME": str(SIGNED_IN), "PATH": f"{r.home / '.local/bin'}:{os.environ['PATH']}", "PYTHONDONTWRITEBYTECODE": "1"}
        p = subprocess.run([CODEX, "exec", "--ephemeral", "--skip-git-repo-check", "$compose-workspace --help"], cwd=r.home, env=env,
                           stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=300)
        self.assertIn("usage: compose workspace", p.stdout + p.stderr, p.stderr[-3000:])


def linear_key():
    try: return any(w.get("linear") for w in json.loads((hermetic.REAL / "auth.json").read_text()).get("workspaces", {}).values())
    except (OSError, ValueError): return False


@unittest.skipUnless(CODEX, "codex is not installed")
class CodexFence(unittest.TestCase):
    """The real codex, started with crew_argv's fence in a scratch home, still does a teammate's work."""

    def setUp(self):
        self.repo = Path(tempfile.mkdtemp()).resolve(); self.wt = Path(f"{self.repo}-wt"); self.res = self.repo / ".compose/p/results"
        self.res.mkdir(parents=True); (self.res.parent / "verify.json").write_text("{}")
        for a in (["init", "-q"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "init"], ["worktree", "add", "-q", "-b", "t", str(self.wt)]):
            subprocess.run(["git", "-C", str(self.repo), *a], check=True)

    def codex(self, task, cwd, **env):
        env = {k: v for k, v in os.environ.items() if not k.startswith("HERDR_")} | {"CODEX_HOME": str(SIGNED_IN), "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t", **env}
        # `codex exec` has no -a, so the fence goes before the subcommand (codex 0.163.0 accepts it there)
        argv = [CODEX, *fc_harness.crew_argv("codex", None, "Do exactly what the task says.", ROOT / "SKILL.md", cwd, self.res), "exec", "--ephemeral", "--skip-git-repo-check", task]
        return subprocess.run(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=600)

    def test_commits_from_a_worktree(self):
        p = self.codex("Create a.txt containing a, then git add and git commit it with the message 'fence ok'.", self.wt)
        self.assertIn("fence ok", subprocess.run(["git", "-C", str(self.wt), "log", "--format=%s"], capture_output=True, text=True).stdout, p.stderr[-3000:])

    def test_reports_into_results(self):
        p = self.codex(f"Run: {ROOT}/bin/compose report --repo {self.repo} --project p --as t working hi", self.repo)
        self.assertTrue((self.res / "crew/t.status").is_file(), p.stdout[-3000:])

    def test_runs_unittest_with_its_caches(self):
        (self.wt / "t.py").write_text("import unittest\nclass T(unittest.TestCase):\n    def test_a(self): open('ran', 'w').write('1')\n")
        p = self.codex(f"Run: {sys.executable} -m unittest t", self.wt)
        self.assertEqual(((self.wt / "ran").is_file(), (self.wt / "__pycache__").is_dir()), (True, True), p.stdout[-3000:])

    @unittest.skipUnless(linear_key(), "no Linear key")
    def test_linear_get(self):
        p = self.codex(f"Run: {ROOT}/bin/compose linear get NEB-1515 --any-project", self.repo, COMPOSE_CONFIG=str(hermetic.REAL / "config.json"))
        self.assertIn("NEB-1515", p.stdout.split("\ncodex\n")[-1], p.stdout[-3000:])


@unittest.skipUnless(CODEX and os.environ.get("HERDR_SOCKET_PATH"), "codex or a herdr pane is missing")
class CodexTeammate(unittest.TestCase):
    def test_reports_working(self):
        repo = Path(tempfile.mkdtemp()).resolve(); self.addCleanup(shutil.rmtree, repo, True)
        (repo / ".compose/p/results").mkdir(parents=True); (repo / ".compose/p/verify.json").write_text("{}")
        crew = [ROOT / "bin/compose.py", "crew", "--repo", str(repo), "--project", "p"]
        env = {**os.environ, "HERDR_ENV": "1", "CODEX_HOME": str(SIGNED_IN)}  # a real teammate reports `working`
        subprocess.run([sys.executable, *crew, "start", "--role", "tester", "--title", "t", "--model", "codex", "--brief", "Report working with the text hi, then stop."], env=env, check=True, timeout=300)
        self.addCleanup(subprocess.run, [sys.executable, *crew, "stop", "--role", "tester", "--force"], env=env)
        status = next((repo / ".compose/p/results/crew").glob("*.status"))
        for _ in range(120):
            if '"message": "hi"' in status.read_text(): return
            time.sleep(2)
        self.fail(status.read_text())


if __name__ == "__main__":
    unittest.main()
