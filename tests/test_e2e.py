import hermetic  # first: no test sees the real home
import importlib.machinery, importlib.util, json, os, shutil, subprocess, tempfile, time, unittest
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
    def verify(self, **flags):
        repo = Path(tempfile.mkdtemp())
        for args in (["init", "-q", "-b", "main"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "init"]):
            subprocess.run(["git", *args], cwd=repo, check=True)
        proj = repo / ".compose" / "p"
        proj.mkdir(parents=True)
        (proj / "verify.json").write_text(json.dumps({"checks": [f"touch {repo}/checked"], "review": False, "jev_acceptance": False,
                                                      "e2e": [{"name": "probe", "driver": f"touch {repo}/driven"}]}))
        a = SimpleNamespace(**{"repo": str(repo), "project": "p", "skip_e2e": False, "skip_review": False, "fix": 2, **flags})
        with mock.patch.object(fc.fc_core, "project_dir", return_value=proj), self.assertRaises(SystemExit) as cm:
            fc.fc_verify.cmd_verify(a)
        return cm.exception.code, repo

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


if __name__ == "__main__":
    unittest.main()
