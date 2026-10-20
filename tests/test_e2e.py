import hermetic  # first: no test sees the real home
import contextlib, importlib.machinery, importlib.util, io, json, os, shutil, subprocess, tempfile, time, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import checkout_bp
CHECKOUT_BP = checkout_bp.use_checkout_bp()
os.environ["COMPOSE_E2E_HEADLESS"] = "1"  # testing the tool itself never opens a browser window; real projects keep theirs
os.environ["HERDR_ENV"] = ""

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)

DETACHED = "python3 -c \"import os,subprocess; subprocess.Popen(['python3','-m','http.server',os.environ['E2E_CLIENT_PORT']],start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)\""


FAKE_CHROMIUM = """#!/usr/bin/env python3
# Chromium's debug port alone: /json/version answers on --remote-debugging-port, headless when launched with --headless
import json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
port = next(int(a.split("=", 1)[1]) for a in sys.argv if a.startswith("--remote-debugging-port="))
browser = ("HeadlessChrome" if any(a.startswith("--headless") for a in sys.argv) else "Chrome") + "/150.0.0.0"
class Version(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({"Browser": browser, "User-Agent": f"Mozilla/5.0 {browser}"}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(body)
    def log_message(self, *a): pass
HTTPServer(("127.0.0.1", port), Version).serve_forever()
"""


class E2eLifecycle(unittest.TestCase):
    """An e2e stage ends everything it started, so no server or browser answers the next round."""
    def stage(self, cfg):
        report, findings = {"e2e": []}, []
        ok = fc.fc_verify.e2e_stage(Path(self.dir), cfg, {}, report, findings)
        return ok, report, findings

    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def alive(self, pid):
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False

    def test_setup_processes_and_detached_listeners_are_gone_afterwards(self):
        ports = Path(self.dir) / "ports"
        setup = (f"echo $E2E_PORT $E2E_CLIENT_PORT > {ports}; sleep 300 & echo $! > {self.dir}/sleep.pid; "
                 f"python3 -m http.server $E2E_PORT >/dev/null 2>&1 & {DETACHED}; sleep 300")
        cfg = {"e2e_setup": setup, "e2e_setup_wait": 2,
               "e2e": [{"name": "probe", "driver": "curl -sf -o /dev/null http://127.0.0.1:$E2E_PORT/ && curl -sf -o /dev/null http://127.0.0.1:$E2E_CLIENT_PORT/"}]}
        ok, report, _ = self.stage(cfg)
        self.assertTrue(ok, report)
        server, client = map(int, ports.read_text().split())
        time.sleep(0.5)
        self.assertFalse(fc.fc_core.port_listening(server))
        self.assertFalse(fc.fc_core.port_listening(client))  # detached from the setup's group, like `bp launch`
        self.assertFalse(self.alive(int((Path(self.dir) / "sleep.pid").read_text())))

    def test_the_cases_start_once_the_ports_their_setup_names_accept(self):
        late = "sleep 1; exec python3 -m http.server {} >/dev/null 2>&1"  # a server still starting when the configured wait is over
        probe = "curl -sf -o /dev/null http://127.0.0.1:$E2E_PORT/ && curl -sf -o /dev/null http://127.0.0.1:$E2E_CLIENT_PORT/"
        ok, report, _ = self.stage({"e2e_setup": late.format("$E2E_PORT"), "e2e_setup_wait": 0,
                                    "e2e": [{"name": "late", "driver": probe, "setup": late.format("$E2E_CLIENT_PORT"), "setup_wait": 0}]})
        self.assertTrue(ok, report)

    def test_every_stage_gets_fresh_ports(self):
        seen = []
        for _ in range(2):
            out = Path(self.dir) / "p"
            self.stage({"e2e": [{"name": "p", "driver": f"echo $E2E_PORT >> {out}"}]})
            seen = out.read_text().split()
        self.assertEqual(len(set(seen)), 2)

    def test_the_stage_launches_and_ends_its_own_browser(self):
        chromium = Path(os.environ["HOME"]) / "chromium"  # the fake stands in for Playwright's Chromium, which bp launches
        chromium.write_text(FAKE_CHROMIUM); chromium.chmod(0o755)
        p = mock.patch.dict(os.environ, {"BP_CHROME": str(chromium)}); p.start(); self.addCleanup(p.stop)
        out = Path(self.dir) / "cdp"
        ua = Path(self.dir) / "ua"
        ok, report, _ = self.stage({"e2e": [{"name": "b", "driver": f"curl -sf $BU_CDP_URL/json/version > {ua} && echo $BU_CDP_URL $BU_NAME > {out}"}]})
        self.assertTrue(ok, report)
        self.assertIn("Headless", ua.read_text())  # no window on the product owner's screen
        url, name = out.read_text().split()
        port = int(url.rsplit(":", 1)[1])
        self.assertNotIn(port, (9222, 9333))  # never the product owner's Chrome or a fixed shared port
        self.assertTrue(name)
        time.sleep(0.5)
        self.assertFalse(fc.fc_core.port_listening(port))

    def test_a_project_without_a_browser_launches_none(self):
        launched = Path(self.dir) / "launched"
        chromium = Path(os.environ["HOME"]) / "chromium"
        chromium.write_text(f"#!/bin/sh\necho started >> {launched}\nsleep 5\n"); chromium.chmod(0o755)
        p = mock.patch.dict(os.environ, {"BP_CHROME": str(chromium)}); p.start(); self.addCleanup(p.stop)
        out = Path(self.dir) / "cdp"
        ok, report, _ = self.stage({"e2e_browser": False, "e2e": [{"name": "d", "driver": f"echo ${{BU_CDP_URL:-none}} > {out}"}]})
        self.assertTrue(ok, report)
        self.assertFalse(launched.exists())
        self.assertEqual(out.read_text().strip(), "none")

    def test_a_configured_browser_is_used_instead(self):
        out = Path(self.dir) / "cdp"
        self.stage({"e2e_env": {"BU_CDP_URL": "http://127.0.0.1:1", "BU_NAME": "ext"},
                    "e2e": [{"name": "b", "driver": f"echo $BU_CDP_URL $BU_NAME > {out}"}]})
        self.assertEqual(out.read_text().split(), ["http://127.0.0.1:1", "ext"])

    def test_a_driver_case_runs_its_assert_after_the_driver(self):
        out = Path(self.dir) / "assert"
        ok, report, findings = self.stage({"e2e": [{"name": "a", "driver": "true", "assert": f"echo $E2E_PORT $PWD > {out}; echo 'no row' >&2; false"}]})
        self.assertFalse(ok)
        self.assertIn("no row", findings[0])
        port, cwd = out.read_text().split()
        self.assertTrue(port.isdigit())
        self.assertEqual(Path(cwd).resolve(), Path(self.dir).resolve())
        ok, _, _ = self.stage({"e2e": [{"name": "a", "driver": "true", "assert": "true"}]})
        self.assertTrue(ok)

    def test_a_case_line_shows_the_run_only_when_the_driver_reports_one(self):
        result = 'echo \'E2E_RESULT {"steps": 3, "elapsed_ms": 40, "status": "done"}\''
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.stage({"e2e_env": {"BU_CDP_URL": "http://127.0.0.1:1", "BU_NAME": "ext"},
                        "e2e": [{"name": "bare", "driver": "true"}, {"name": "run", "driver": result}]})
        lines = [l for l in out.getvalue().splitlines() if "e2e    ok" in l]
        self.assertTrue(lines[0].endswith("  bare"), lines)
        self.assertTrue(lines[1].endswith("  run  steps=3 run=40ms status=done"), lines)

    def test_a_failing_driver_skips_its_assert(self):
        out = Path(self.dir) / "assert"
        ok, _, _ = self.stage({"e2e": [{"name": "a", "driver": "exit 1", "assert": f"touch {out}"}]})
        self.assertFalse(ok)
        self.assertFalse(out.exists())


class ToolErrors(unittest.TestCase):
    def test_a_harness_crash_is_retried_once_and_never_a_finding(self):
        d = tempfile.mkdtemp()
        crash = f"echo x >> {d}/n; echo 'File \"/x/jev_ultrafast/model.py\", line 193' >&2; exit 1"
        report, findings = {"e2e": []}, []
        ok = fc.fc_verify.e2e_stage(Path(d), {"e2e": [{"name": "c", "driver": crash}]}, {}, report, findings)
        self.assertFalse(ok)
        self.assertEqual(findings, [])
        self.assertTrue(report["e2e"][0]["tool_error"])
        self.assertEqual(len((Path(d) / "n").read_text().split()), 2)

    def test_an_app_failure_is_a_finding(self):
        report, findings = {"e2e": []}, []
        ok = fc.fc_verify.e2e_stage(Path(tempfile.mkdtemp()), {"e2e": [{"name": "a", "driver": "echo 'AssertionError: no line' >&2; exit 1"}]}, {}, report, findings)
        self.assertFalse(ok)
        self.assertEqual(len(findings), 1)
        self.assertFalse(report["e2e"][0]["tool_error"])

    def check(self, cmd):
        with mock.patch.object(fc.fc_herdr, "herdr_verify_panes", return_value={}):
            return fc.fc_verify.run_stages(Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp()), {"checks": [cmd]}, SimpleNamespace(skip_e2e=True, skip_review=True))

    def test_a_failing_check_whose_early_output_names_a_harness_error_is_one_run_and_a_finding(self):
        d = tempfile.mkdtemp()
        noisy = f"echo x >> {d}/n; echo 'Chromium not found at /x'; python3 -c \"print('.' * 4000)\"; echo 'FAILED (failures=1)'; exit 1"
        ok, report, findings = self.check(noisy)
        self.assertFalse(ok)
        self.assertEqual(len((Path(d) / "n").read_text().split()), 1)
        self.assertFalse(report["checks"][0]["tool_error"])
        self.assertIn("FAILED (failures=1)", findings)

    def test_a_check_that_ends_on_a_harness_error_is_retried_once_and_never_a_finding(self):
        d = tempfile.mkdtemp()
        ok, report, findings = self.check(f"echo x >> {d}/n; echo 'bash: nosuchtool: command not found' >&2; exit 127")
        self.assertFalse(ok)
        self.assertEqual(len((Path(d) / "n").read_text().split()), 2)
        self.assertTrue(report["checks"][0]["tool_error"])
        self.assertEqual(findings, "")


class FixRoundChecks(unittest.TestCase):
    def stages(self, scoped, full, tests):
        """run_stages with its checks and a fix round's tests each appending their name to one log, in run order."""
        d = Path(tempfile.mkdtemp())
        cmd = lambda name, code: f"echo {name} >> {d}/log; exit {code}"
        with mock.patch.object(fc.fc_herdr, "herdr_verify_panes", return_value={}):
            ok, report, findings = fc.fc_verify.run_stages(d, d, {"checks": [cmd("full", full)]}, SimpleNamespace(skip_e2e=True, skip_review=True),
                                                           None if tests is None else [cmd("scoped", scoped)])
        return ok, report, findings, (d / "log").read_text().split()

    def test_a_fix_round_runs_its_tests_then_every_check_once(self):
        ok, report, findings, log = self.stages(0, 0, tests=True)
        self.assertEqual((ok, log, findings), (True, ["scoped", "full"], ""))
        self.assertEqual([len(report["scoped"]), len(report["checks"])], [1, 1])  # the PR body reads only the full checks

    def test_a_failing_fix_test_skips_the_full_checks(self):
        ok, report, findings, log = self.stages(1, 0, tests=True)
        self.assertEqual((ok, log, report["checks"]), (False, ["scoped"], []))
        self.assertIn("echo scoped", findings)

    def test_a_regression_the_fix_tests_miss_fails_the_round(self):
        ok, _, findings, log = self.stages(0, 1, tests=True)
        self.assertEqual((ok, log), (False, ["scoped", "full"]))
        self.assertIn("echo full", findings)

    def test_the_first_round_runs_only_the_full_checks(self):
        ok, report, _, log = self.stages(0, 0, tests=None)
        self.assertEqual((ok, log, report["scoped"]), (True, ["full"], []))


class CheckoutBp(unittest.TestCase):
    """The suite runs the checkout's bp, whatever bp sits on PATH."""
    target = os.path.realpath(Path(__file__).resolve().parents[1] / "bp" / "bin" / "bp.mjs")

    def stale(self, dangling):
        d = Path(tempfile.mkdtemp())
        if dangling:
            (d / "bp").symlink_to(d / "gone.mjs")
        else:
            (d / "bp").write_text("#!/bin/sh\necho other\n")
            (d / "bp").chmod(0o755)
        return str(d)

    def test_the_import_put_the_checkout_bp_first(self):
        self.assertEqual(os.environ["PATH"].split(os.pathsep)[0], CHECKOUT_BP)
        self.assertEqual(os.path.realpath(shutil.which("bp")), self.target)

    def test_it_wins_over_a_dangling_or_different_bp_ahead_and_keeps_the_rest_in_order(self):
        for dangling in (True, False):
            rest = [self.stale(dangling), "/usr/bin", "/bin"]
            with mock.patch.dict(os.environ, {"PATH": os.pathsep.join(rest)}):
                d = checkout_bp.use_checkout_bp()
                self.assertEqual(d, CHECKOUT_BP)
                self.assertEqual(os.environ["PATH"].split(os.pathsep), [d] + rest)
                self.assertEqual(os.path.realpath(shutil.which("bp")), self.target)

    def test_a_second_call_returns_the_same_dir_and_path_holds_it_once(self):
        rest = ["/usr/bin", "/bin"]
        with mock.patch.dict(os.environ, {"PATH": os.pathsep.join([rest[0], CHECKOUT_BP, rest[1]])}):
            first, second = checkout_bp.use_checkout_bp(), checkout_bp.use_checkout_bp()
            self.assertEqual(first, second)
            self.assertEqual(os.environ["PATH"].split(os.pathsep), [first] + rest)

    def test_the_dir_is_outside_the_checkout_and_holds_only_bp(self):
        self.assertFalse(Path(CHECKOUT_BP).resolve().is_relative_to(Path(__file__).resolve().parents[1]))
        self.assertEqual(os.listdir(CHECKOUT_BP), ["bp"])
        self.assertTrue(os.access(Path(CHECKOUT_BP) / "bp", os.X_OK))


class BeforePlanning(unittest.TestCase):
    """Groundwork writes checks and e2e cases before any task exists; verify runs them without a sync when nothing reads the tasks."""
    TASK = {"id": "001", "title": "a", "files": ["x.py"], "protected": ["t.py"], "test": "true", "body": "## Goal\nx"}

    def verify(self, tasks=None, checks=None, last=None, **flags):
        repo = Path(tempfile.mkdtemp())
        for args in (["init", "-q", "-b", "main"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "init"]):
            subprocess.run(["git", *args], cwd=repo, check=True)
        self.proj = proj = repo / ".compose" / "p"
        (proj / "results").mkdir(parents=True)
        (proj / "verify.json").write_text(json.dumps({"checks": checks or [f"touch {repo}/checked"], "review": False, "jev_acceptance": False,
                                                      "e2e": [{"name": "probe", "driver": f"touch {repo}/driven"}]}))
        if tasks is not None:
            (proj / "results" / "tasks.json").write_text(json.dumps({"feature": {}, "tasks": tasks}))
        if last is not None:
            (proj / "results" / "verify.json").write_text(last)
        a = SimpleNamespace(**{"repo": str(repo), "project": "p", "skip_e2e": False, "skip_review": False, "fix": 2, **flags})
        self.out = io.StringIO()
        with mock.patch.object(fc.fc_core, "project_dir", return_value=proj), mock.patch.object(fc.fc_linear, "linear_reconcile") as self.lr, \
                mock.patch.object(fc.fc_verify, "verify_failed") as self.vf, contextlib.redirect_stdout(self.out), self.assertRaises(SystemExit) as cm:
            fc.fc_verify.cmd_verify(a)
        return cm.exception.code, repo

    def smoke(self, label, **kw):
        code, _ = self.verify(**kw)
        final = [l for l in self.out.getvalue().splitlines() if f"smoke {label}" in l or "verify PASS" in l or "verify FAIL" in l]
        self.assertEqual(len(final), 1, self.out.getvalue()); self.assertIn(f"smoke {label}", final[0])
        self.assertEqual(self.lr.call_count, 0)
        return code, json.loads((self.proj / "results" / "smoke.json").read_text())

    def test_an_unsynced_or_empty_sync_run_is_a_smoke_run_and_writes_no_verify_record(self):
        for kw, left_out in (({"skip_review": True, "fix": 0}, ["tasks", "review"]), ({"tasks": []}, ["tasks"]),
                             ({"tasks": [], "skip_e2e": True, "fix": 0}, ["tasks", "e2e"])):
            code, smoke = self.smoke(f"PASS ({', '.join('no ' + x for x in left_out)})", **kw)
            self.assertEqual((code, smoke["left_out"], smoke["passed"], len(smoke["rounds"])), (0, left_out, True, 1), kw)
            self.assertFalse((self.proj / "results" / "verify.json").exists(), kw)

    def test_a_skipped_stage_is_a_smoke_run_that_leaves_the_last_verify_record_alone(self):
        for kw, left_out in (({"skip_review": True}, ["review"]), ({"skip_e2e": True, "skip_review": True}, ["review", "e2e"]),
                             ({"skip_e2e": True, "checks": ["false"], "fix": 0}, ["e2e"])):
            label = ("FAIL" if "checks" in kw else "PASS") + f" ({', '.join('no ' + x for x in left_out)})"
            code, smoke = self.smoke(label, tasks=[self.TASK], last='{"passed": true}', **kw)
            self.assertEqual((code, smoke["left_out"], {"rejected_fixes", "seconds", "cost"} <= smoke.keys()), (1 if "checks" in kw else 0, left_out, True), kw)
            record = self.proj / "results" / "verify.json"
            self.assertEqual(record.read_text(), '{"passed": true}', kw)

    def test_a_synced_run_with_no_skip_flag_is_a_full_verify_even_with_review_and_e2e_off_in_its_config(self):
        code, _ = self.verify(tasks=[self.TASK])
        record = json.loads((self.proj / "results" / "verify.json").read_text())
        self.assertEqual((code, record["passed"], "left_out" in record), (0, True, False))
        self.assertFalse((self.proj / "results" / "smoke.json").exists())
        self.assertIn("verify PASS", self.out.getvalue()); self.assertNotIn("smoke", self.out.getvalue())
        self.assertEqual(self.lr.call_args_list, [mock.call(self.proj, verified=True)])

    def test_checks_and_e2e_run_unsynced_with_no_review_and_no_fixer(self):
        code, repo = self.verify(skip_review=True, fix=0)
        self.assertEqual(code, 0)
        self.assertTrue((repo / "checked").exists() and (repo / "driven").exists())

    def test_a_verify_that_reviews_or_fixes_still_needs_the_sync_and_names_the_way_without(self):
        for flags in ({}, {"skip_review": True}, {"fix": 0}):
            code, repo = self.verify(**flags)
            self.assertIn("no tasks synced for p", str(code), flags)
            self.assertIn("--skip-review --fix 0", str(code), flags)
            self.assertFalse((repo / "checked").exists(), flags)

    def test_a_smoke_fail_skips_the_failure_screen_and_keeps_its_record_line_and_exit(self):
        for kw, label in (({"skip_review": True}, "no tasks, no review"), ({"tasks": []}, "no tasks"),
                          ({"tasks": [self.TASK], "skip_e2e": True}, "no e2e"), ({"tasks": [self.TASK], "skip_review": True, "last": '{"passed": true}'}, "no review")):
            code, smoke = self.smoke(f"FAIL ({label})", checks=["false"], fix=0, **kw)
            self.assertEqual((code, smoke["passed"], self.vf.call_count), (1, False, 0), kw)

    def test_a_full_verify_fail_still_screens_its_rounds_and_findings(self):
        code, _ = self.verify(tasks=[self.TASK], checks=["false"], fix=0, last='{"passed": true}')
        record = json.loads((self.proj / "results" / "verify.json").read_text())
        self.assertEqual((code, record["passed"], self.vf.call_count), (1, False, 1))
        proj, rounds, findings = self.vf.call_args.args
        self.assertEqual((proj, len(rounds), rounds[0]["checks"]), (self.proj, 1, record["rounds"][0]["checks"]))
        self.assertIn("Command failed: false", findings)
        self.assertIn("verify FAIL", self.out.getvalue())

    def test_a_passing_run_never_reaches_the_failure_screen(self):
        for kw in ({"tasks": [self.TASK]}, {"tasks": []}, {"skip_review": True, "fix": 0}):
            code, _ = self.verify(**kw)
            self.assertEqual((code, self.vf.call_count), (0, 0), kw)


T = 1_760_000_000  # fixed mtimes: the other record is 3 hours off, so its HH:MM never matches

def hm(t):
    return time.strftime("%H:%M", time.localtime(t))

class SmokeStatus(unittest.TestCase):
    def line(self, smoke=None, verify=None):
        """Each record is (dict, mtime); returns the project line of render_status."""
        repo = Path(tempfile.mkdtemp()); proj = repo / ".compose" / "p"; (proj / "results").mkdir(parents=True)
        for name, rec in (("smoke.json", smoke), ("verify.json", verify)):
            if rec:
                (proj / "results" / name).write_text(json.dumps(rec[0])); os.utime(proj / "results" / name, (rec[1], rec[1]))
        with mock.patch.object(fc.fc_tasks, "load_tasks", return_value=[]), mock.patch.object(fc.fc_core, "current_branch", return_value="main"), \
                mock.patch.object(fc.fc_core, "sh", return_value=SimpleNamespace(stdout="abc\n", returncode=0)), \
                mock.patch.object(fc.fc_worktree, "stack_order", return_value=[]), mock.patch.object(fc.fc_cost, "rows", return_value=[]):
            return fc.fc_status.render_status(repo, [proj]).splitlines()[0]

    def test_smoke_alone_shows_smoke(self):
        line = self.line(smoke=({"passed": True, "seconds": 2.0, "left_out": ["tasks"]}, T))
        self.assertIn(f"  smoke PASS (no tasks) 2.0s at {hm(T)}", line)
        self.assertNotIn("verify", line)

    def test_newer_smoke_wins_with_its_own_label_time_and_seconds(self):
        line = self.line(smoke=({"passed": True, "seconds": 125.6, "left_out": ["review", "e2e"]}, T), verify=({"passed": True, "seconds": 12.3}, T - 3 * 3600))
        self.assertIn(f"  smoke PASS (no review, no e2e) 2m05.6s at {hm(T)}", line)
        self.assertNotIn("verify", line)

    def test_newer_verify_wins_as_today(self):
        line = self.line(smoke=({"passed": True, "seconds": 2.0, "left_out": ["tasks", "review"]}, T - 3 * 3600), verify=({"passed": False, "seconds": 12.3}, T))
        self.assertTrue(line.endswith(f"0 tasks:   verify FAIL 12.3s at {hm(T)}"), line)
        self.assertNotIn("smoke", line)

    def test_failed_smoke_says_fail(self):
        line = self.line(smoke=({"passed": False, "seconds": 0.4, "left_out": ["tasks", "e2e"]}, T), verify=({"passed": True, "seconds": 12.3}, T - 3 * 3600))
        self.assertIn(f"  smoke FAIL (no tasks, no e2e) 0.4s at {hm(T)}", line)
        self.assertNotIn("PASS", line)


if __name__ == "__main__":
    unittest.main()
