import importlib.machinery, importlib.util, os, tempfile, time, unittest
from pathlib import Path
import sys
os.environ["FAST_CODING_E2E_HEADLESS"] = "1"  # testing the tool itself never opens a browser window; real projects keep theirs

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "fast_coding.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)

DETACHED = "python3 -c \"import os,subprocess; subprocess.Popen(['python3','-m','http.server',os.environ['E2E_CLIENT_PORT']],start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)\""


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


if __name__ == "__main__":
    unittest.main()
