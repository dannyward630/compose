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


if __name__ == "__main__":
    unittest.main()
