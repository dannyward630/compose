import hermetic  # first: no test sees the real home
import importlib.machinery, importlib.util, json, os, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
os.environ["HERDR_ENV"] = ""

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)
import fc_notify

TOPIC = "https://ntfy.example/topic-abc"


class Notify(unittest.TestCase):
    """A phone notification is opt-in, one line, and never stops a run."""
    def setUp(self):
        self.proj = Path(tempfile.mkdtemp()) / "hw"
        (self.proj / "results").mkdir(parents=True)
        fc.fc_config.CONFIG_PATH.unlink(missing_ok=True)  # the path is fixed at import: a test's config must not outlive it
        self.addCleanup(fc.fc_config.CONFIG_PATH.unlink, missing_ok=True)
        self.sent = []
        def urlopen(req, timeout=None):
            self.sent.append(req)
            return mock.MagicMock()
        for p in (mock.patch("urllib.request.urlopen", urlopen), mock.patch.dict(os.environ, {k: v for k, v in os.environ.items() if k != "COMPOSE_ROLE"}, clear=True)):
            p.start(); self.addCleanup(p.stop)

    def config(self, cfg):
        fc.fc_config.CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        fc.fc_config.CONFIG_PATH.write_text(json.dumps(cfg))

    def away(self, push=False):
        (self.proj / "results" / "yolo.json").write_text(json.dumps({"mode": "away", "push": push}))

    def test_nothing_is_sent_without_a_notify_block_or_with_one_that_is_not_a_url(self):
        for cfg in ({}, {"notify": {}}, {"notify": {"ntfy": ""}}, {"notify": {"ntfy": "topic"}}, {"notify": "https://x"}):
            self.config(cfg)
            self.assertFalse(fc_notify.send(self.proj, "payment required"), cfg)
        self.assertEqual(self.sent, [])

    def test_one_line_goes_to_the_topic_with_the_project_slug_as_title_and_no_secret(self):
        self.config({"notify": {"ntfy": TOPIC}})
        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-or-v1-" + "a" * 40}):
            self.assertTrue(fc_notify.send(self.proj, "payment required\nkey sk-or-v1-" + "a" * 40))
        (req,) = self.sent
        self.assertEqual((req.full_url, req.get_method(), req.get_header("Title")), (TOPIC, "POST", "compose hw"))
        self.assertNotIn(b"\n", req.data)
        self.assertNotIn(b"sk-or-v1-" + b"a" * 40, req.data)

    def test_a_workspace_notify_replaces_the_top_level_topic(self):
        self.config({"notify": {"ntfy": "https://ntfy.example/top"}, "workspace": "w", "workspaces": {"w": {"notify": {"ntfy": TOPIC}}}})
        fc_notify.send(self.proj, "x")
        self.assertEqual(self.sent[0].full_url, TOPIC)

    def test_a_topic_that_does_not_answer_is_not_an_error(self):
        self.config({"notify": {"ntfy": TOPIC}})
        with mock.patch("urllib.request.urlopen", side_effect=OSError("offline")):
            self.assertFalse(fc_notify.send(self.proj, "x"))

    def attention(self, *events):
        with mock.patch.object(fc.fc_crew, "desktop_notify"):
            fc.fc_crew.manager_attention(self.proj, list(events))
        lines = [r.data.decode() for r in self.sent]
        self.sent.clear()
        return lines

    def test_a_payment_halt_notifies_with_the_provider_and_nothing_from_the_error(self):
        self.config({"notify": {"ntfy": TOPIC}})
        proj = Path(tempfile.mkdtemp()) / ".compose" / "hw"; (proj / "results").mkdir(parents=True)
        with mock.patch("builtins.print"), self.assertRaises(SystemExit):
            fc.fc_models.payment_halt(proj.parent.parent, proj, "run", ["001"], {}, fc.fc_models.PaymentRequired("openrouter", "secret detail"))
        (req,) = self.sent
        self.assertIn("payment required at openrouter", req.data.decode())
        self.assertNotIn("secret detail", req.data.decode())

    def test_gates_only_the_owner_can_clear_notify_and_the_rest_do_not(self):
        self.config({"notify": {"ntfy": TOPIC}})
        self.assertEqual(self.attention("event task=001 state=passed", "event verify=FAIL", "event crew=hw-a state=working message='x'"), [])
        self.assertEqual(len(self.attention("event agent=hw-001 status=blocked  (read: x)")), 1)
        self.assertEqual(self.attention("event crew=hw-a state=needs-user message='sign in to Stripe'"), [])  # not away: the desktop alert covers it
        self.away()
        (line,) = self.attention("event crew=hw-a state=needs-user message='please sign in to Figma sk-live-123'")
        self.assertIn("hw-a", line)
        self.assertNotIn("Figma", line)
        self.assertNotIn("sk-live-123", line)
        self.assertEqual(self.attention("event crew=hw-a state=needs-user message='Stripe or Adyen? I recommend Stripe'"), [])  # the posture answers it
        self.assertIn("push approval", self.attention("event verify=PASS")[0])
        self.away(push=True)
        self.assertEqual(self.attention("event verify=PASS"), [])

    def test_a_teammates_session_sends_nothing(self):
        self.config({"notify": {"ntfy": TOPIC}})
        with mock.patch.dict(os.environ, {"COMPOSE_ROLE": "orchestrator"}):
            self.assertEqual(self.attention("event agent=hw-001 status=blocked"), [])

    def test_with_no_notify_block_the_watch_path_sends_nothing(self):
        self.away()
        self.assertEqual(self.attention("event agent=hw-001 status=blocked", "event verify=PASS"), [])


if __name__ == "__main__":
    unittest.main()
