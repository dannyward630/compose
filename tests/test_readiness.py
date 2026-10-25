import hermetic  # first: no test sees the real home
import unittest
import importlib.machinery, importlib.util, os, sys
from pathlib import Path
os.environ["HERDR_ENV"] = ""

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)
import fc_readiness  # noqa: E402

FEATURE = '## Intent\n\nA shop.\n\n## Decisions so far\n\n- D1: the design on ENG-1 is approved (product owner, 2026-10-20; said: "yes")\n'
STORY = "## Intent\n\nPay by card.\n\n## Acceptance criteria\n\n- a card payment succeeds\n"


def labels(names):
    return {"nodes": [{"name": n} for n in names]}


def tree(story=STORY, labels_=(), feature=FEATURE, feature_labels=("Feature",), epic=None, epic_labels=("Epic",), docs=(), state="Todo", tasks=(), blockers=()):
    epic_node = None if epic is None else {"id": "e", "identifier": "ENG-0", "title": "Payments", "description": epic, "labels": labels(epic_labels)}
    return {"id": "s", "identifier": "ENG-7", "title": "Pay", "description": story, "state": {"name": state}, "labels": labels(labels_),
            "children": {"nodes": list(tasks)}, "inverseRelations": {"nodes": list(blockers)},
            "project": {"documents": {"nodes": list(docs)}},
            "parent": {"id": "f", "identifier": "ENG-1", "title": "Shop", "description": feature, "labels": labels(feature_labels), "parent": epic_node}}


class Gates(unittest.TestCase):
    def test_a_specced_story_passes_every_gate(self):
        self.assertEqual(fc_readiness.gates(fc_readiness.story_chain(tree())), [])

    def test_open_cards_and_their_open_questions_block_but_readiness_lines_do_not(self):
        mine = STORY + "\n## Open questions\n\n* Where does ENG-7 stop? (readiness check, 2026-10-25)\n"
        self.assertEqual(fc_readiness.gates(fc_readiness.story_chain(tree(story=mine))), [])
        theirs = mine + "* Which card brands?\n"
        self.assertEqual([x["question"] for x in fc_readiness.gates(fc_readiness.story_chain(tree(story=theirs)))],
                         ["ENG-7 has open questions waiting for the product owner (1)."])
        carded = STORY + "\n## Not yet specified\n\nQ1. Which processor?\n"
        self.assertEqual([x["item"] for x in fc_readiness.gates(fc_readiness.story_chain(tree(story=carded)))], ["cards"])

    def test_deep_dive_on_the_epic_needs_its_tech_doc_linked_and_approved(self):
        epic = "## Intent\n\nPayments.\n"
        g = fc_readiness.gates(fc_readiness.story_chain(tree(epic=epic, epic_labels=("Epic", "Deep-Dive"))))
        self.assertEqual([(x["item"], x["issue"]) for x in g], [("tech doc", "ENG-0")])
        doc = {"title": "ENG-0: tech doc", "content": "Use Stripe intents.", "url": "https://linear.app/d/1"}
        linked = epic + "\n## Tech doc\n\nhttps://linear.app/d/1\n"
        self.assertIn("not approved yet", fc_readiness.gates(fc_readiness.story_chain(tree(epic=linked, epic_labels=("Epic", "deep-dive"), docs=[doc])))[0]["question"])
        approved = linked + '\n## Decisions so far\n\n- D1: the tech doc on ENG-0 is approved (product owner, 2026-10-24; said: "ok")\n'
        self.assertEqual(fc_readiness.gates(fc_readiness.story_chain(tree(epic=approved, epic_labels=("Epic", "deep-dive"), docs=[doc]))), [])

    def test_an_unlinked_tech_doc_is_reported(self):
        epic = '## Decisions so far\n\n- D1: the tech doc on ENG-0 is approved (po, 2026-10-24; said: "ok")\n'
        doc = {"title": "ENG-0: tech doc", "content": "x", "url": "https://linear.app/d/1"}
        g = fc_readiness.gates(fc_readiness.story_chain(tree(epic=epic, epic_labels=("Epic", "deep-dive"), docs=[doc])))
        self.assertEqual([x["question"] for x in g], ["ENG-0's tech doc is not linked under ## Tech doc."])

    def test_a_task_or_a_feature_is_refused(self):
        with self.assertRaisesRegex(fc_readiness.NotAStory, "ENG-7 is a task"):
            fc_readiness.story_chain(tree(story=STORY + "\n```compose\nid: 07\ntest: t\n```\n"))
        with self.assertRaisesRegex(fc_readiness.NotAStory, "is not a story"):
            fc_readiness.story_chain(tree(feature_labels=()))

    def test_no_or_too_many_criteria_is_a_criteria_gap_on_the_story(self):
        g = fc_readiness.gates(fc_readiness.story_chain(tree(story="## Intent\n\nPay.\n")))
        self.assertEqual([(x["item"], x["issue"]) for x in g], [("criteria", "ENG-7")])
        self.assertIn("no acceptance criteria", g[0]["question"])
        many = "## Acceptance criteria\n\n" + "".join(f"- c{i}\n" for i in range(6))
        g = fc_readiness.gates(fc_readiness.story_chain(tree(story=many)))
        self.assertIn("6 acceptance criteria (at most 5)", g[0]["question"])

    def test_an_unapproved_or_struck_design_blocks(self):
        for feature in ("## Intent\n\nA shop.\n",
                        "## Decisions so far\n\n- ~~D1: the design on ENG-1 is approved (po, 2026-10-20; said: \"yes\")~~ (C1)\n"):
            g = fc_readiness.gates(fc_readiness.story_chain(tree(feature=feature)))
            self.assertEqual([(x["item"], x["issue"]) for x in g], [("design", "ENG-1")])



import json  # noqa: E402
import fc_claude, fc_core, fc_models  # noqa: E402
from unittest import mock  # noqa: E402

STATE = {"story": {"id": "ENG-7", "title": "Pay", "description": STORY}, "feature": FEATURE, "epic": "", "tech_docs": []}


class Judge(unittest.TestCase):
    def setUp(self):
        self.jev, self.asked = {}, []

        def ask(env, cfg, state, questions, label):
            self.asked = list(questions)
            return {"answers": {k: {"choice": c, "probabilities": {c: p}} for k, (c, p) in self.jev.items() if k in questions}}
        for p in (mock.patch.object(fc_models, "jev_ask", ask), mock.patch.object(fc_models, "fast_env", return_value={"TYPESAFE_API_KEY": "k"})):
            p.start(); self.addCleanup(p.stop)
        p = mock.patch.object(fc_claude, "claude_json"); self.strong = p.start(); self.addCleanup(p.stop)

    def test_jev_judges_a_product_story_and_a_weak_ready_counts_as_missing(self):
        self.jev = {"intent": ("READY", 0.9), "scope": ("READY", 0.55), "testable": ("UNCLEAR", 0.7), "context": ("READY", 0.8), "kind": ("PRODUCT", 0.9)}
        out = fc_readiness.judge(STATE, "ENG-7", deep_dive=False)
        self.assertEqual(out["judge"], "jev")
        self.assertFalse(out["technical"])
        self.assertEqual([m["question"] for m in out["missing"]],
                         ["Where does ENG-7 stop: what is in it and what is left out?", "How would we check each acceptance criterion on ENG-7?"])
        self.assertEqual(sorted(self.asked), ["context", "intent", "kind", "scope", "testable"])
        self.strong.assert_not_called()

    def test_a_technical_story_is_judged_again_by_the_stronger_model_whose_verdict_wins(self):
        self.jev = {**{k: ("READY", 0.9) for k in ("intent", "scope", "testable", "context")}, "kind": ("TECHNICAL", 0.7)}
        self.strong.return_value = json.dumps({"items": {"intent": {"ready": True, "missing": ""}, "scope": {"ready": True, "missing": ""},
                                                         "testable": {"ready": True, "missing": ""}, "context": {"ready": False, "missing": "Which queue carries the retries?"}}})
        out = fc_readiness.judge(STATE, "ENG-7", deep_dive=False)
        self.assertEqual((out["technical"], out["judge"]), (True, "claude:claude-opus-5-5"))
        self.assertEqual(out["missing"], [{"item": "context", "issue": "ENG-7", "question": "Which queue carries the retries?"}])
        self.assertEqual(self.strong.call_args.kwargs["effort"], "high")

    def test_deep_dive_asks_grounding_and_goes_to_the_stronger_model_whatever_jev_says(self):
        self.jev = {"kind": ("PRODUCT", 0.95)}
        items = {k: {"ready": True, "missing": ""} for k in ("intent", "scope", "testable", "context", "grounding")}
        self.strong.return_value = json.dumps({"items": items})
        out = fc_readiness.judge(STATE, "ENG-7", deep_dive=True)
        self.assertIn("grounding", self.asked)
        self.assertIn("grounding", json.loads(self.strong.call_args.args[1])["items"])
        self.assertTrue(out["technical"])
        self.assertEqual(out["missing"], [])

    def test_a_judge_that_cannot_answer_raises(self):
        with mock.patch.object(fc_models, "jev_ask", side_effect=RuntimeError("HTTP 503")), self.assertRaisesRegex(RuntimeError, "503"):
            fc_readiness.judge(STATE, "ENG-7", deep_dive=False)
        self.jev = {"kind": ("TECHNICAL", 0.9)}
        self.strong.return_value = "not json"
        with self.assertRaises(RuntimeError):
            fc_readiness.judge(STATE, "ENG-7", deep_dive=False)
        self.strong.return_value = json.dumps({"items": {k: {"ready": True, "missing": ""} for k in ("intent", "testable", "context")}})
        with self.assertRaisesRegex(RuntimeError, "scope"):
            fc_readiness.judge(STATE, "ENG-7", deep_dive=False)

    def test_the_state_keeps_the_story_whole_and_cuts_the_tech_docs_first(self):
        doc = {"title": "ENG-7: tech doc", "content": "x" * 40000, "url": "u"}
        chain = fc_readiness.story_chain(tree(labels_=("deep-dive",), docs=[doc]))
        state = fc_readiness.judge_state(chain)
        self.assertLessEqual(len(json.dumps(state)), fc_readiness.STATE_CAP)
        self.assertIn("Pay by card.", state["story"]["description"])
        self.assertIn("A shop.", state["feature"])
        asked = STORY + "\n## Open questions\n\n* Which brands?\n"
        self.assertNotIn("Open questions", fc_readiness.judge_state(fc_readiness.story_chain(tree(story=asked)))["story"]["description"])

    def test_a_secret_in_the_story_text_does_not_reach_the_stronger_model(self):
        self.jev = {"kind": ("TECHNICAL", 0.9)}
        self.strong.return_value = json.dumps({"items": {k: {"ready": True, "missing": ""} for k in ("intent", "scope", "testable", "context")}})
        state = {**STATE, "story": {**STATE["story"], "description": "use key sk-live-0123456789abcdef"}}
        with mock.patch.dict(fc_core.os.environ, {"OPENROUTER_API_KEY": "sk-live-0123456789abcdef"}):
            fc_readiness.judge(state, "ENG-7", deep_dive=False)
        sent = " ".join(str(a) for a in self.strong.call_args.args)
        self.assertNotIn("sk-live-0123456789abcdef", sent)
        self.assertIn("<redacted>", sent)


class ClaudeJson(unittest.TestCase):
    def test_claude_json_passes_effort(self):
        for effort, want in (("high", True), (None, False)):
            with mock.patch.object(fc_claude.fc_proc, "run", return_value=mock.Mock(stdout='{"result": "{}"}', stderr="", returncode=0)) as run:
                fc_claude.claude_json("s", "u", "claude:claude-opus-5-5", effort=effort)
            cmd = run.call_args.args[0]
            self.assertEqual("--effort" in cmd, want)
            if want:
                self.assertEqual(cmd[cmd.index("--effort") + 1], "high")


if __name__ == "__main__":
    unittest.main()
