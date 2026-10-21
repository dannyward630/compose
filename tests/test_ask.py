import hermetic  # first: no test sees the real home
import contextlib, http.server, importlib.machinery, importlib.util, io, json, os, sys, tempfile, threading, unittest
from pathlib import Path
from unittest import mock
os.environ["HERDR_ENV"] = ""

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)


class Page(http.server.BaseHTTPRequestHandler):
    """Answers like lavish-axi's server: its real session answers, a made-up one is a 404."""
    def do_GET(self):
        self.send_response(200 if self.path == "/session/4433ea54b6a63d29" else 404)
        self.end_headers()

    def log_message(self, *args):
        pass


class Ask(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Page)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        cls.good = f"{cls.base}/session/4433ea54b6a63d29"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.proj = Path(tempfile.mkdtemp()) / ".compose" / "shop"
        (self.proj / "results" / "crew").mkdir(parents=True)

    def report(self, msg, state="needs-user", who="shop-wayfinder"):
        out = io.StringIO()
        with mock.patch.object(fc.fc_core, "project_dir", return_value=self.proj), contextlib.redirect_stdout(out):
            fc.fc_crew.cmd_report(type("A", (), {"as_": who, "state": state, "message": msg.split()}))
        return out.getvalue()

    def sent(self):
        return [r["message"] for r in fc.fc_crew.crew_reports(self.proj, "shop-wayfinder")]

    def test_card_ids_expand_ranges_and_lists(self):
        ids = fc.fc_ask.card_ids
        self.assertEqual(ids("NEB-1: 7 cards W1-W7; recommendation accept"), [f"W{n}" for n in range(1, 8)])
        self.assertEqual(ids("NEB-1: 4 cards Q1-Q2, Q5 and Q7; rec"), ["Q1", "Q2", "Q5", "Q7"])
        self.assertEqual(ids("NEB-1: 3 cards Q1 to Q3"), ["Q1", "Q2", "Q3"])
        self.assertEqual(ids("which fixture? I recommend A"), [])
        self.assertEqual(ids("NEB-1: 2 cards"), [])

    def test_a_working_link_goes_out_with_the_text_fallback(self):
        self.report(f"NEB-1: 2 cards V1-V2; recommendation accept; visual cards open in Lavish: {self.good}")
        (msg,) = self.sent()
        self.assertIn(self.good, msg)
        self.assertTrue(msg.endswith(fc.fc_ask.ASK_FALLBACK))

    def test_a_link_that_does_not_answer_is_refused_and_nothing_is_sent(self):
        for url in (f"{self.base}/session/0123456789abcdef", "http://127.0.0.1:9/session/4433ea54b6a63d29"):
            with self.assertRaises(SystemExit) as e:
                self.report(f"NEB-1: 1 cards V1; recommendation a; visual cards open in Lavish: {url}")
            self.assertIn("does not answer", str(e.exception))
        self.assertEqual(self.sent(), [])

    def test_one_page_in_two_host_forms_is_refused(self):
        other = self.good.replace("127.0.0.1", "localhost")
        with self.assertRaises(SystemExit) as e:
            self.report(f"NEB-1: 1 cards V1; recommendation a; visual cards open in Lavish: {self.good} or {other}")
        self.assertIn("2 forms", str(e.exception))
        self.assertEqual(self.sent(), [])

    def test_a_visual_page_without_its_link_is_refused(self):
        with self.assertRaises(SystemExit) as e:
            self.report("NEB-1: 1 cards V1; recommendation a; visual cards open in Lavish: /tmp/x/lavish/wayfinder.html")
        self.assertIn("lavish-axi <file>", str(e.exception))
        self.assertEqual(self.sent(), [])

    def test_other_needs_user_lines_and_states_are_untouched(self):
        self.report("Which payment provider? I recommend Stripe")
        self.report("Frame0 asks to allow the MCP server: click Allow")
        self.report(f"working {self.base}/session/0123456789abcdef", state="working")
        self.assertEqual(len(self.sent()), 3)

    def test_the_same_open_cards_are_asked_once(self):
        ask = "NEB-1: 3 cards Q1-Q3; recommendation accept-all"
        self.report(ask)
        out = self.report(ask)
        self.assertIn("already asked", out)
        self.assertEqual(self.sent(), [ask])
        self.assertEqual(sorted(json.loads((self.proj / "results" / "asked.json").read_text())), ["/NEB-1/Q1", "/NEB-1/Q2", "/NEB-1/Q3"])

    def test_one_reminder_is_allowed_then_no_more(self):
        ask = "NEB-1: 2 cards Q1-Q2; recommendation accept-all"
        self.report(ask)
        self.report("reminder: " + ask)
        out = self.report("reminder: " + ask)
        self.assertIn("reminder is spent", out)
        self.assertEqual(self.sent(), [ask, "reminder: " + ask])
        self.assertNotIn("already asked", self.report("NEB-1: 1 cards Q9; recommendation a"))

    def test_new_cards_go_out_with_the_old_ones_in_one_ask(self):
        self.report("NEB-1: 2 cards Q1-Q2; recommendation a")
        self.report("NEB-1: 3 cards Q1-Q3; recommendation a")
        self.assertEqual(len(self.sent()), 2)
        self.assertIn("already asked", self.report("NEB-1: 1 cards Q3; recommendation a"))

    def test_the_same_ids_on_another_issue_or_change_are_new_cards(self):
        self.report("NEB-1: 1 cards Q1; recommendation a")
        self.report("NEB-2: 1 cards Q1; recommendation a")
        self.report("change C1: NEB-1: 1 cards Q1; recommendation a")
        self.assertEqual(len(self.sent()), 3)

    def test_cards_already_decided_on_the_map_are_never_asked(self):
        (self.proj / "linear.json").write_text(json.dumps({"feature": "NEB-1"}))
        desc = "## Decisions so far\n- Q1: Stripe (product owner, 2026-10-20)\n- ~~Q2: old~~\n- Q3: no (yolo recommendation, unconfirmed, 2026-10-20)\n\n## Not yet specified\n- Q2: ?\n"
        gql = mock.Mock(return_value={"issue": {"description": desc}})
        with mock.patch.object(fc.fc_config, "LINEAR_KEY", "k"), mock.patch.object(fc.fc_linear, "linear_gql", gql):
            out = self.report("NEB-1: 2 cards Q1, Q3; recommendation a")
            self.assertIn("already in the map's Decisions so far", out)
            self.assertEqual(self.sent(), [])
            self.report("NEB-1: 3 cards Q1-Q3; recommendation a")
        self.assertEqual(len(self.sent()), 1)
        self.assertEqual(sorted(json.loads((self.proj / "results" / "asked.json").read_text())), ["/NEB-1/Q2"])

    def test_a_linear_outage_does_not_stop_an_ask(self):
        with mock.patch.object(fc.fc_config, "LINEAR_KEY", "k"), mock.patch.object(fc.fc_linear, "linear_gql", side_effect=OSError("down")):
            self.report("NEB-1: 1 cards Q1; recommendation a")
        self.assertEqual(len(self.sent()), 1)


class Briefs(unittest.TestCase):
    def test_wayfinder_and_change_briefs_carry_the_ask_rules(self):
        for brief in (fc.fc_briefs.WAYFINDER_BRIEF, fc.fc_briefs.CHANGE_BRIEF):
            flat = " ".join(brief.split())
            for want in ("visual cards open in Lavish: <url>", "`url:`", "--takeover", "180000 ms", "lavish-axi reply {page} --agent-reply",
                         "`browser_disconnected`", "reminder:", "`yolo:`", "(yolo recommendation, unconfirmed, <date>)"):
                self.assertIn(want, flat)
            self.assertNotIn("\u2014", brief)

    def test_planner_brief_names_unconfirmed_yolo_lines(self):
        flat = " ".join(fc.fc_briefs.PLANNER_BRIEF.split())
        self.assertIn("(yolo recommendation, unconfirmed, <date>)", flat)
        self.assertIn("Built on unconfirmed: <card ids>", flat)


if __name__ == "__main__":
    unittest.main()
