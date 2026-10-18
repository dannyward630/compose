import hermetic  # first: no test sees the real home
import importlib.machinery, importlib.util, json, os, tempfile, unittest
from pathlib import Path
from unittest import mock
import sys, time
os.environ["HERDR_ENV"] = ""

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)


class AgentNames(unittest.TestCase):
    def test_agent_name(self):
        self.assertEqual(fc.fc_herdr.agent_name("custom-dropdowns", "001"), "custom-dropdowns-001")
        self.assertEqual(fc.fc_herdr.agent_name("Workday Login!", "012"), "workday-login-012")
        long = fc.fc_herdr.agent_name("a" * 40, "003")
        self.assertEqual(len(long), 32)
        self.assertTrue(long.endswith("-003"))
        self.assertTrue(fc.fc_herdr.agent_name("9lives", "001").startswith("fc-9lives"))

    def test_a_cut_name_is_still_the_projects(self):
        slug = "clean-recut-branches"  # 20 characters: its team lead's name is cut to 32, its groundwork's is not
        lead = fc.fc_herdr.agent_name(slug, "orchestrator")
        self.assertEqual(lead, "clean-recut-branche-orchestrator")
        self.assertEqual(fc.fc_herdr.agent_id(slug, lead), "orchestrator")
        self.assertEqual(fc.fc_herdr.agent_id(slug, "clean-recut-branches-groundwork"), "groundwork")
        self.assertEqual(fc.fc_herdr.agent_id(slug, "clean-recut-branches-tests-001"), "tests-001")
        self.assertIsNone(fc.fc_herdr.agent_id(slug, "clean-bugs-orchestrator"))
        for ref in ("orchestrator", lead, "clean-recut-branches-orchestrator"):  # the role, the registered name, the name the docs spell out
            self.assertEqual(fc.fc_herdr.agent_ref(slug, ref), lead)

    def test_herdr_noop_outside(self):
        with mock.patch.dict(os.environ, {"HERDR_ENV": ""}):
            self.assertIsNone(fc.fc_herdr.herdr("agent", "list"))

    def test_implementer_routes_headless_outside_herdr(self):
        with mock.patch.dict(os.environ, {"HERDR_ENV": ""}), mock.patch.object(fc.fc_models, "pi_turn", return_value=("s", "t", 0, {})) as pt:
            fc.fc_implement.implementer("/tmp", "pi:x/y", "hi", None, task={"space": "w9"})
            pt.assert_called_once()


def line(**msg):
    return json.dumps({"type": "message", "message": msg})


class PiSession(unittest.TestCase):
    def test_parse_turns(self):
        f = Path(tempfile.mkdtemp()) / "s.jsonl"
        f.write_text("\n".join([
            json.dumps({"type": "session", "id": "x"}),
            line(role="user", content=[{"type": "text", "text": "do it"}]),
            line(role="assistant", stopReason="toolUse", content=[{"type": "toolCall", "name": "edit"}],
                 usage={"input": 100, "output": 10, "cacheRead": 5, "cacheWrite": 0, "reasoning": 2, "cost": {"total": 0.01}}),
            line(role="toolResult", content=[{"type": "text", "text": "ok"}]),
            line(role="assistant", stopReason="stop", content=[{"type": "text", "text": "done"}],
                 usage={"input": 50, "output": 5, "cacheRead": 0, "cacheWrite": 0, "reasoning": 0, "cost": {"total": 0.002}}),
        ]) + "\n")
        seen, text, tools, usage, errors = fc.fc_models.parse_pi_session(f, 0)
        self.assertEqual((seen, text, tools, errors), (5, "done", 1, []))
        self.assertEqual((usage["tokens_in"], usage["tokens_out"]), (155, 17))
        self.assertAlmostEqual(usage["cost"], 0.012)
        seen2, text2, tools2, usage2, _ = fc.fc_models.parse_pi_session(f, seen)
        self.assertEqual((seen2, text2, tools2, usage2["tokens_in"]), (5, "", 0, 0))

    def test_parse_pi_session_error(self):
        f = Path(tempfile.mkdtemp()) / "s.jsonl"
        f.write_text(line(role="assistant", stopReason="error", errorMessage="402 Payment Required: insufficient credits", content=[]) + "\n")
        with self.assertRaises(fc.fc_models.PaymentRequired):
            fc.fc_models.parse_pi_session(f, 0)


class Watch(unittest.TestCase):
    def snap(self, **tasks):
        return {"tasks": {k: {"state": v, "attempts": 1, "cost": 0.01, "note": "", "linear": "ENG-7", "title": "T"} for k, v in tasks.items()},
                "agents": {}, "run": True, "verify": None}

    def test_task_final_and_running_are_events_attempts_are_not(self):
        a, b = self.snap(**{"001": "running"}), self.snap(**{"001": "passed"})
        ev = fc.fc_watch.watch_events(a, b)
        self.assertEqual(len(ev), 1)
        self.assertIn("task=001 state=passed", ev[0]); self.assertIn("linear=ENG-7", ev[0])
        b["tasks"]["001"]["attempts"] = 2; b["tasks"]["001"]["state"] = "running"
        self.assertEqual(fc.fc_watch.watch_events(self.snap(**{"001": "running"}), b), [])
        self.assertIn("state=running", fc.fc_watch.watch_events(self.snap(**{"001": "pending"}), self.snap(**{"001": "running"}))[0])

    def test_agent_blocked_run_ended_verify(self):
        a, b = self.snap(**{"001": "passed"}), self.snap(**{"001": "passed"})
        b["agents"] = {"demo-001": "blocked"}; b["run"] = False; b["verify"] = (1, True)
        ev = fc.fc_watch.watch_events(a, b)
        self.assertTrue(any("agent=demo-001 status=blocked" in e for e in ev))
        self.assertTrue(any("run=ended passed=1/1" in e for e in ev))
        self.assertTrue(any("verify=PASS" in e for e in ev))
        self.assertEqual(fc.fc_watch.watch_events(b, b), [])

    def test_pid_alive(self):
        self.assertTrue(fc.fc_tasks.pid_alive(os.getpid()))
        self.assertFalse(fc.fc_tasks.pid_alive(2**22 + 12345))
        self.assertFalse(fc.fc_tasks.pid_alive(None))


class Tabs(unittest.TestCase):
    """Implementers share one tab, one pane each; verify reuses one tab. A space never grows a tab per task or per run."""
    def fake(self, tabs, panes):
        calls = []
        def herdr(*args, check=False, timeout=120):
            calls.append(args)
            if args[:2] == ("tab", "list"):
                return {"tabs": [{"label": l, "tab_id": t} for l, t in tabs.items()]}
            if args[:2] == ("pane", "list"):
                return {"panes": panes}
            if args[:2] == ("tab", "create"):
                return {"tab": {"tab_id": "w9:t9"}, "root_pane": {"pane_id": "w9:p1"}}
            if args[:2] == ("pane", "split"):
                return {"pane": {"pane_id": f"w9:p{len(calls)}"}}
        return calls, herdr

    def test_first_implementer_creates_the_tab_later_ones_split_it(self):
        calls, h = self.fake({}, [])
        with mock.patch.object(fc.fc_herdr, "herdr", h):
            self.assertEqual(fc.fc_herdr.herdr_implementer_pane("w9", "/tmp", {"K": "v"}), "w9:p1")
        self.assertIn("implementers", calls[-1]); self.assertIn("K=v", calls[-1])
        for n, direction in ((1, "right"), (2, "down")):
            panes = [{"pane_id": f"w9:p{i}", "tab_id": "w9:t9"} for i in range(1, n + 1)] + [{"pane_id": "w9:pX", "tab_id": "w9:t1"}]
            calls, h = self.fake({"implementers": "w9:t9"}, panes)
            with mock.patch.object(fc.fc_herdr, "herdr", h):
                fc.fc_herdr.herdr_implementer_pane("w9", "/tmp", {})
            split = calls[-1]
            self.assertEqual(split[:3], ("pane", "split", f"w9:p{n}"))
            self.assertIn(direction, split)
            self.assertFalse(any(c[:2] == ("tab", "create") for c in calls))

    def test_verify_replaces_its_previous_tab(self):
        calls, h = self.fake({"verify": "w9:t2", "verify 12:10": "w9:t3", "status": "w9:t4"}, [])
        with mock.patch.object(fc.fc_herdr, "herdr", h):
            fc.fc_herdr.herdr_verify_panes("w9", "/tmp", ["checks"])
        closed = [c[2] for c in calls if c[:2] == ("tab", "close")]
        self.assertEqual(sorted(closed), ["w9:t2", "w9:t3"])



class SharedSpace(unittest.TestCase):
    """A project opens as a worktree space of its own grouped under its repo's open space; with none open, in the space compose was
    started from: no new space, its tabs named for it, found again by every later command."""
    spaces, repo_space = [{"workspace_id": "w7", "label": "apps", "worktree": {"checkout_path": "/elsewhere"}}], None

    def herdr(self, *args, check=False, timeout=120):
        self.calls.append(args)
        if args[:2] == ("workspace", "list"):
            return {"workspaces": self.spaces}
        if args[:2] == ("worktree", "list"):  # `source_workspace_id` is the repo's open space, absent when none is
            return {"source": {"source_workspace_id": self.repo_space} if self.repo_space else {}}
        if args[:2] == ("worktree", "open"):
            self.spaces = [*self.spaces, {"workspace_id": "w9", "label": "shop", "worktree": {"checkout_path": args[args.index("--path") + 1]}}]
            return {"workspace": {"workspace_id": "w9"}}
        if args[:2] == ("tab", "list"):
            return {"tabs": [{"tab_id": t, "label": l} for t, l in self.tabs.items()]}
        if args[:2] == ("tab", "create"):
            tid = f"w7:t{len(self.tabs) + 1}"
            self.tabs[tid] = args[args.index("--label") + 1]
            return {"tab": {"tab_id": tid}, "root_pane": {"pane_id": f"w7:p{len(self.tabs)}"}}
        return {}

    def space(self, caller):
        fc.fc_herdr.HERDR_SPACES.clear()
        with mock.patch.object(fc.fc_herdr, "herdr", self.herdr), mock.patch.object(fc.fc_herdr, "herdr_env", return_value=True), \
                mock.patch.dict(os.environ, {"HERDR_WORKSPACE_ID": caller}):
            return fc.fc_herdr.herdr_space(self.proj)

    def test_init_puts_the_project_in_the_callers_space_and_later_commands_find_it(self):
        wt = Path(tempfile.mkdtemp()).resolve()
        self.proj, self.tabs, self.calls = wt / ".compose" / "shop", {"w7:t1": "1"}, []
        (self.proj / "results").mkdir(parents=True)
        self.assertEqual(self.space("w7"), "w7")
        self.assertFalse([c for c in self.calls if c[:2] in (("worktree", "open"), ("workspace", "create"), ("workspace", "rename"), ("tab", "rename"))])
        self.assertEqual(sorted(self.tabs.values()), ["1", "shop shell", "shop status"])  # the caller's own tab is left as it is
        self.assertTrue(all(str(wt) in c for c in self.calls if c[:2] == ("tab", "create")))
        self.assertEqual(fc.fc_herdr.tab_label(self.proj, "implementers"), "shop implementers")
        self.calls = []
        self.assertEqual(self.space("w18"), "w7")  # a teammate in another space still finds the project's
        self.assertFalse([c for c in self.calls if c[:2] == ("tab", "create")])

    def test_a_space_open_on_the_projects_repo_gets_the_worktree_as_its_own_space_grouped_under_it(self):
        wt = Path(tempfile.mkdtemp()).resolve()
        self.proj = wt / ".compose" / "shop"
        (self.proj / "results").mkdir(parents=True)
        self.repo_space = "w3"
        for caller in ("w3", "w7"):  # started from the repo's own space, and from another repo's while the repo's is open
            self.spaces, self.tabs, self.calls = SharedSpace.spaces, {"w3:t1": "1"}, []
            self.assertEqual(self.space(caller), "w9")
            self.assertIn(("worktree", "open", "--workspace", "w3", "--path", str(wt), "--label", "shop", "--no-focus"), self.calls)
            self.assertEqual({c[c.index("--workspace") + 1] for c in self.calls if c[:2] == ("tab", "create")}, {"w9"})
            self.assertFalse(fc.fc_herdr.space_record(self.proj).exists())
            self.assertEqual(fc.fc_herdr.tab_label(self.proj, "implementers"), "implementers")
            self.calls = []
            self.assertEqual(self.space("w18"), "w9")  # a teammate in another space finds it, and nothing is opened again
            self.assertFalse([c for c in self.calls if c[:2] in (("worktree", "open"), ("tab", "create"))])


class NoHerdr(unittest.TestCase):
    """COMPOSE_NO_HERDR=1 keeps every command headless inside herdr too: init and verify open no space, tab, or pane."""
    def test_init_and_verify_never_call_herdr(self):
        import subprocess
        d = Path(tempfile.mkdtemp()).resolve(); (d / "bin").mkdir(); (d / "r").mkdir()
        log, repo = d / "herdr.log", d / "r"
        (d / "bin" / "herdr").write_text(f"#!/bin/sh\necho \"$*\" >> {log}\necho '{{\"result\": {{\"root_pane\": {{\"pane_id\": \"w1:p9\"}}}}}}'\n")
        (d / "bin" / "herdr").chmod(0o755)
        git = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        subprocess.run("git init -q -b main && git commit -q --allow-empty -m init", shell=True, cwd=repo, check=True, env={**os.environ, **git})
        inside = {**git, "PATH": f"{d / 'bin'}{os.pathsep}{os.environ['PATH']}", "HERDR_ENV": "1", "HERDR_SOCKET_PATH": str(d / "sock"),
                  "HERDR_WORKSPACE_ID": "w1", "COMPOSE_NO_TRAIL": "1"}
        for off in (True, False):
            env, name = inside | ({"COMPOSE_NO_HERDR": "1"} if off else {}), "off" if off else "on"
            log.unlink(missing_ok=True)
            subprocess.run([str(Path(__file__).resolve().parents[1] / "bin" / "compose"), "init", "--here", "--project", name, "--repo", str(repo)],
                           cwd=repo, check=True, capture_output=True, env={**os.environ, **env})
            with mock.patch.dict(os.environ, env):
                fc.fc_herdr.HERDR_SPACES.clear()
                fc.fc_herdr.herdr_verify_panes("w1", repo, ["checks"], fc.fc_herdr.tab_label(repo / ".compose" / name, "verify"))
            calls = log.read_text() if log.exists() else ""
            if off:  # the setup checks still ask herdr its version and integrations; nothing touches the session
                self.assertEqual([c for c in calls.splitlines() if c.split()[0] in ("workspace", "worktree", "tab", "pane", "agent")], [])
            else:  # the same commands without the variable do reach herdr: the fake is on the path
                self.assertIn("tab create --workspace w1 --label on shell", calls)
                self.assertIn("--label on verify", calls)


FAKE_HERDR = """#!{py}
import json, os, subprocess, sys
state, args = {state!r}, sys.argv[1:]
panes = json.load(open(state)) if os.path.exists(state) else {{}}
def env_of(a):
    return dict(a[i + 1].split("=", 1) for i in range(len(a) - 1) if a[i] == "--env")
if args[:2] == ["tab", "list"]:
    print(json.dumps({{"result": {{"tabs": []}}}}))
elif args[:2] in (["tab", "create"], ["pane", "split"], ["workspace", "create"]):
    pane = f"w1:p{{len(panes) + 1}}"; panes[pane] = env_of(args); json.dump(panes, open(state, "w"))
    print(json.dumps({{"result": {{"root_pane": {{"pane_id": pane}}, "pane": {{"pane_id": pane}}, "workspace": {{"workspace_id": "w1"}}}}}}))
elif args[:2] == ["pane", "run"]:  # the pane's shell has the server's env plus what its creation passed, never the caller's
    subprocess.run(["sh", "-c", args[3]], env={{"PATH": os.environ["PATH"], "HOME": {server_home!r}, **panes[args[2]]}})
    print(json.dumps({{"result": {{}}}}))
else:
    print(json.dumps({{"result": {{}}}}))
"""


class CallerEnv(unittest.TestCase):
    """A pane compose opens through herdr gets the herdr server's env, not the caller's: a scratch COMPOSE_CONFIG and HOME
    must travel with it, or the CLI it runs there works on the real ~/.compose."""
    def test_a_scratch_config_and_home_reach_the_panes_command(self):
        d = Path(tempfile.mkdtemp()); (d / "bin").mkdir()
        herdr = d / "bin" / "herdr"
        herdr.write_text(FAKE_HERDR.format(py=sys.executable, state=str(d / "panes.json"), server_home=str(d / "real-home")))
        me = d / "compose"  # stands in for the CLI the status pane runs: records the env it got
        me.write_text(f"#!{sys.executable}\nimport json, os\nopen({str(d / 'seen.json')!r}, 'w').write(json.dumps([os.environ.get('COMPOSE_CONFIG'), os.environ['HOME']]))\n")
        herdr.chmod(0o755); me.chmod(0o755)
        caller = {"PATH": f"{d / 'bin'}{os.pathsep}{os.environ['PATH']}", "HERDR_ENV": "1", "HERDR_SOCKET_PATH": str(d / "sock"),
                  "COMPOSE_CONFIG": str(d / "scratch" / "config.json"), "HOME": str(d / "scratch-home")}
        with mock.patch.dict(os.environ, caller), mock.patch.object(sys, "argv", [str(me)]):
            fc.fc_herdr.herdr_status_tab("w1", d, "demo")
            fc.fc_herdr.herdr_implementer_pane("w1", d, {"K": "v"})
            fc.fc_herdr.herdr("workspace", "create", "--cwd", str(d), "--label", "demo")
        self.assertEqual(json.loads((d / "seen.json").read_text()), [caller["COMPOSE_CONFIG"], caller["HOME"]])
        for env in json.loads((d / "panes.json").read_text()).values():  # the status tab, an implementer pane (crew tabs too), a space's shell
            self.assertEqual((env["COMPOSE_CONFIG"], env["HOME"]), (caller["COMPOSE_CONFIG"], caller["HOME"]))

    def test_the_pane_id_stays_right_after_pane_split(self):
        # herdr 0.9.5 reads `pane split`'s pane id only as its first argument: `pane split --env K=V w4:p5 ...` is "unknown option: w4:p5"
        with mock.patch.dict(os.environ, {"COMPOSE_CONFIG": "/s/config.json", "HOME": "/s/home"}):
            self.assertEqual(fc.fc_herdr.herdr_argv(["pane", "split", "w4:p5", "--direction", "down", "--no-focus"]),
                             ["herdr", "pane", "split", "w4:p5", "--direction", "down", "--no-focus",
                              "--env", "COMPOSE_CONFIG=/s/config.json", "--env", "HOME=/s/home"])


class AgentStartRace(unittest.TestCase):
    def test_a_busy_pane_is_retried_until_it_is_ready(self):
        answers = iter([(None, "agent_pane_busy"), (None, "agent_pane_busy"), ({"agent": {"name": "a"}}, None)])
        with mock.patch.object(fc.fc_herdr, "herdr_error", lambda *a, **k: next(answers)), mock.patch.object(time, "sleep"):
            self.assertEqual(fc.fc_herdr.herdr_agent_start("a", "--pane", "p1"), {"agent": {"name": "a"}})

    def test_an_unregistered_name_is_retried(self):
        answers = iter([(None, "agent_name_not_found"), ({"agent": {"name": "a"}}, None)])
        with mock.patch.object(fc.fc_herdr, "herdr_error", lambda *a, **k: next(answers)), mock.patch.object(time, "sleep"):
            self.assertEqual(fc.fc_herdr.herdr_agent_start("a", "--pane", "p1"), {"agent": {"name": "a"}})

    def test_other_errors_and_a_pane_that_never_frees_still_fail(self):
        with mock.patch.object(fc.fc_herdr, "herdr_error", return_value=(None, "pane_not_found")) as e, mock.patch.object(time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "pane_not_found"):
                fc.fc_herdr.herdr_agent_start("a")
            self.assertEqual(e.call_count, 1)
        with mock.patch.object(fc.fc_herdr, "herdr_error", return_value=(None, "agent_pane_busy")) as e, mock.patch.object(time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "agent_pane_busy"):
                fc.fc_herdr.herdr_agent_start("a", tries=3)
            self.assertEqual(e.call_count, 3)


class StackLock(unittest.TestCase):
    def test_parallel_linearize_calls_never_overlap(self):
        """Parallel tasks with `after:` all linearize in the one stack worktree; overlapping git there crashed a run."""
        import threading as th
        active, overlaps = [0], []
        def fake(*a):
            active[0] += 1
            if active[0] > 1:
                overlaps.append(1)
            __import__('time').sleep(0.05)
            active[0] -= 1
            return []
        with mock.patch.object(fc.fc_layers, "_linearize", fake):
            ts = [th.Thread(target=fc.fc_layers.linearize, args=(None, None, "t", None)) for _ in range(4)]
            [t.start() for t in ts]; [t.join() for t in ts]
        self.assertEqual(overlaps, [])


class WatchCrash(unittest.TestCase):
    def test_a_dead_run_with_its_marker_left_is_an_ended_run(self):
        proj = Path(tempfile.mkdtemp()); (proj / "results").mkdir()
        (proj / "results" / "run.json").write_text(json.dumps({"pid": 999999}))
        self.assertFalse(fc.fc_tasks.run_alive(proj))
        before = {"tasks": {}, "agents": {}, "run": True, "verify": None}
        after = {"tasks": {}, "agents": {}, "run": fc.fc_tasks.run_alive(proj), "crashed": True, "verify": None}
        ev = fc.fc_watch.watch_events(before, after)
        self.assertEqual(len(ev), 1); self.assertIn("run=ended", ev[0]); self.assertIn("CRASHED", ev[0])


class BareCompose(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[1]

    def run_compose(self, *args, tty=True, herdr=True, claude=False, **env):
        import pty, select, subprocess
        tmp = Path(tempfile.mkdtemp())
        fakebin, nobin, rec = tmp / "bin", tmp / "nobin", tmp / "rec"
        [d.mkdir() for d in (fakebin, nobin, rec)]
        (fakebin / "herdr").write_text("#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$REC/argv\"; pwd > \"$REC/cwd\"\n")
        (nobin / "claude").write_text("#!/bin/sh\nexit 0\n")
        (fakebin / "herdr").chmod(0o755), (nobin / "claude").chmod(0o755)
        path = ":".join([str(fakebin)] * herdr + [str(nobin)] * claude + ["/usr/bin:/bin"])
        base = {k: v for k, v in os.environ.items() if k not in ("CI", "COMPOSE_NO_HERDR") and not k.startswith(("HERDR_", "ANTHROPIC_"))}
        base |= {"HOME": str(tmp), "COMPOSE_CONFIG": str(tmp / "config.json")}
        master, slave = pty.openpty()
        io = {"stdin": slave, "stdout": slave} if tty else {"stdin": subprocess.DEVNULL, "stdout": subprocess.PIPE}
        p = subprocess.Popen([sys.executable, str(self.ROOT / "bin" / "compose"), *args], stderr=subprocess.PIPE, cwd=tmp,
                             env=base | {"PATH": path, "REC": str(rec), "NO_COLOR": "1"} | env, **io)
        os.close(slave)
        out = b""
        while tty and select.select([master], [], [], 10)[0]:
            try:
                chunk = os.read(master, 4096)
            except OSError:  # EIO once the child closed the pty (macOS)
                break
            if not chunk:
                break
            out += chunk
        piped, err = p.communicate(timeout=20)
        os.close(master)
        return p.returncode, out.decode() + (piped or b"").decode(), err.decode(), rec, tmp

    def test_attaches_in_current_directory(self):
        for env in ({}, {"CI": "", "HERDR_ENV": "", "COMPOSE_NO_HERDR": ""}):
            code, out, err, rec, tmp = self.run_compose(**env)
            self.assertEqual(code, 0, err)
            self.assertIn("opening herdr session compose: run claude in a pane and type /compose", out)
            self.assertEqual((rec / "argv").read_text().split("\n"), ["session", "attach", "compose", ""])
            self.assertEqual(os.path.realpath((rec / "cwd").read_text().strip()), os.path.realpath(tmp))

    def test_failing_condition_prints_usage(self):
        for kw in ({"tty": False}, {"HERDR_ENV": "1"}, {"CI": "1"}, {"COMPOSE_NO_HERDR": "1"}, {"CI": "false"}):
            code, out, err, rec, _ = self.run_compose(**kw)
            self.assertEqual(code, 2, kw)
            self.assertIn("usage: compose", err)
            self.assertNotIn("opening herdr", out)
            self.assertFalse((rec / "argv").exists(), kw)

    def test_herdr_missing(self):
        for claude in (False, True):
            code, out, err, rec, _ = self.run_compose(herdr=False, claude=claude)
            self.assertEqual(code, 1)
            self.assertIn("herdr is not installed: curl -fsSL https://herdr.dev/install.sh | sh", err)
            self.assertIn("or run compose setup", err)

    def test_subcommands_never_attach(self):
        for args in (["--help"], ["tasks", "--help"]):
            code, out, err, rec, _ = self.run_compose(*args)
            self.assertEqual(code, 0, err)
            self.assertIn("usage: compose", out)
            self.assertFalse((rec / "argv").exists())


class BareUsage(unittest.TestCase):
    ROOT = BareCompose.ROOT
    compose = BareCompose.run_compose

    def names(self):
        code, _, err, _, _ = self.compose("nosuchcmd", tty=False, COLUMNS="80")
        self.assertEqual(code, 2)
        self.assertIn("invalid choice: 'nosuchcmd'", err)
        return [n.strip(" '") for n in err.split("choose from ")[1].split(")")[0].split(",")]

    def test_bare_prints_every_command_on_its_own_line(self):
        names = self.names()
        self.assertTrue({"doctor", "setup", "workspace"} <= set(names), names)
        for kw in ({"HERDR_ENV": "1"}, {"HERDR_ENV": "1", "tty": False}, {"CI": "1"}, {"COMPOSE_NO_HERDR": "1"}):
            code, out, err, rec, _ = self.compose(COLUMNS="80", **kw)
            self.assertEqual(code, 2, kw)
            self.assertTrue(err.startswith("usage: compose [-h] <command> ..."), err[:200])
            self.assertNotIn("{doctor", err)
            self.assertNotIn("opening herdr", out)
            self.assertFalse((rec / "argv").exists(), kw)
            starts = [l.split()[0] for l in err.splitlines() if l.strip()]
            self.assertEqual([n for n in names if n not in starts], [], kw)
            self.assertEqual([l for l in err.splitlines() if len(l) > 80], [], kw)

    def test_help_and_subcommands_keep_working(self):
        code, out, err, rec, _ = self.compose("--help", HERDR_ENV="1", COLUMNS="80")
        self.assertEqual(code, 0, err)
        self.assertIn("usage: compose [-h] <command> ...", out)
        code, out, err, rec, _ = self.compose("tasks", "--bogus", tty=False, HERDR_ENV="1")
        self.assertEqual(code, 2)
        self.assertIn("usage: compose tasks", err)
        self.assertIn("unrecognized arguments: --bogus", err)


if __name__ == "__main__":
    unittest.main()
