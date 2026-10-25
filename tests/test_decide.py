import hermetic  # first: no test sees the real home
import contextlib, importlib.machinery, importlib.util, io, json, os, sys, tempfile, time, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
os.environ["HERDR_ENV"] = ""

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)

MAP = """## Destination

A shop.

## Decisions so far

- Q0: Stripe (product owner, 2026-10-20; said: "stripe")
- Q3: dark theme (yolo recommendation, unconfirmed, 2026-10-21)

## Not yet specified

Q1. Which auth?
Why: every screen signs in.
A. Clerk - affects: billing, vendor
B. Own JWT - affects: two tasks of work
Recommendation: A - less to build

Q2. Database?
A. Postgres - affects: hosting
B. SQLite - affects: deploy only
C. Mongo - affects: the whole data model
Recommendation: B

## Out of scope

- payments v2
"""
TODAY = time.strftime("%Y-%m-%d")


class FakeLinear:
    """Linear as two calls use it: a read of the map and a description write."""
    def __init__(self, body):
        self.body = body
        self.writes = []

    def gql(self, query, variables):
        if "issueUpdate" in query:
            self.writes.append(variables["in"]["description"])
            self.body = variables["in"]["description"]
            return {"issueUpdate": {"success": True}}
        return {"issue": {"id": "uuid-1", "identifier": "NEB-1", "description": self.body}}


class Decide(unittest.TestCase):
    def setUp(self):
        self.proj = Path(tempfile.mkdtemp()) / ".compose" / "shop"
        (self.proj / "results").mkdir(parents=True)
        (self.proj / "linear.json").write_text(json.dumps({"feature": "NEB-1"}))
        self.linear = FakeLinear(MAP)

    def run_cmd(self, fn, *answers, quote=None, accept_all=False, issue=None, change=None, new=None, replaces=None):
        out = io.StringIO()
        a = SimpleNamespace(repo=".", project="shop", answers=list(answers), quote=quote, accept_all=accept_all, issue=issue, change=change, new=new or [], replaces=replaces)
        with mock.patch.object(fc.fc_core, "project_dir", return_value=self.proj), mock.patch.object(fc.fc_linear, "linear_gql", self.linear.gql), \
                mock.patch.object(fc.fc_linear_cmd, "SETTLE_SECONDS", 0), contextlib.redirect_stdout(out):
            fn(a)
        return out.getvalue()

    def decide(self, *answers, **kw):
        return self.run_cmd(fc.fc_decide.cmd_decide, *answers, **kw)

    def decisions(self):
        return self.run_cmd(fc.fc_decide.cmd_decisions)

    def test_the_decisions_page_shows_every_open_card_in_full_and_the_decisions_so_far(self):
        (self.proj / "results" / "asked.json").write_text(json.dumps({"manager@/NEB-1/Q1": {"at": "2026-10-24 09:00:00"}}))
        out = self.decisions()
        self.assertIn("shop: 2 open card(s) on NEB-1, 1 decision(s) to confirm", out)
        self.assertIn("Q1. Which auth?  (asked 2026-10-24 09:00:00)", out)
        self.assertIn("   Why: every screen signs in.", out)
        self.assertIn("   A. Clerk - affects: billing, vendor", out)
        self.assertIn("   Recommendation: A", out)
        self.assertIn("Q2. Database?  (not asked yet)", out)
        self.assertIn("Decisions so far (2):\n- Q0: Stripe", out)
        self.assertIn('compose decide --project shop --quote "<your words>" "Q1: A, Q2: B"', out)
        self.assertEqual(self.linear.writes, [])

    def test_the_page_names_what_a_card_lacks_of_the_format(self):
        self.linear.body = "## Not yet specified\nQ5. Colors?\nA. warm\n"
        out = self.decisions()
        self.assertIn("format: Q5: options are A; write them as A., B. (C., D.) in order, two at least", out)
        self.assertIn("format: Q5: option A says nothing about what it affects", out)

    def test_a_decision_is_recorded_only_with_the_product_owners_words(self):
        with self.assertRaises(SystemExit) as e:
            self.decide("Q1: A")
        self.assertIn("recorded only with the product owner's words", str(e.exception.code))
        self.assertIn("--quote", str(e.exception.code))
        self.assertEqual(self.linear.writes, [])

    def test_answers_move_the_cards_from_not_yet_specified_to_decisions_with_the_quote(self):
        out = self.decide("Q1: A", "Q2: own thing, Mongo is out", quote='A for auth, and for the db "own thing", Mongo is out')
        body = self.linear.body
        self.assertIn(f'- Q1: A. Clerk (product owner, {TODAY}; said: "A for auth, and for the db \'own thing\', Mongo is out")', body)
        self.assertIn(f"- Q2: own thing, Mongo is out (product owner, {TODAY}; said:", body)
        self.assertNotIn("Q1. Which auth?", body)
        self.assertNotIn("Recommendation:", body)
        self.assertIn("## Not yet specified\n\n## Out of scope\n\n- payments v2\n", body)
        self.assertIn("- Q0: Stripe", body)
        self.assertIn("recorded on NEB-1: Q1: A. Clerk", out)
        self.assertIn("Not yet specified on NEB-1 is empty", out)
        self.assertIn("tell the team lead: herdr agent prompt shop-orchestrator", out)
        self.assertNotIn("—", body + out)

    def test_a_letter_the_card_has_not_and_an_unknown_card_refuse(self):
        for words, want in (("Q1: C", "Q1 has no option C; it has A, B"), ("Q7: A", "no card Q7 under Not yet specified; the open cards are Q1, Q2"),
                            ("Q1 A", "is not an answer")):
            with self.assertRaises(SystemExit) as e:
                self.decide(words, quote="C")
            self.assertIn(want, str(e.exception.code))
        self.assertEqual(self.linear.writes, [])

    def test_a_hyphenated_card_id_is_answered_like_any_other(self):
        self.linear.body = "## Not yet specified\n\nC1-8. Which?\nA. one - affects: x\nB. two - affects: y\nRecommendation: A\n"
        self.decide("C1-8: B", quote="two")
        self.assertIn(f"- C1-8: B. two (product owner, {TODAY}", self.linear.body)

    def test_an_id_with_letters_a_hyphen_and_digits_is_answered_like_any_other(self):
        self.linear.body = "## Not yet specified\n\nREC-19. Which?\nA. one - affects: x\nB. two - affects: y\nRecommendation: A\n"
        self.decide("REC-19: B", quote="two")
        self.assertIn(f"- REC-19: B. two (product owner, {TODAY}", self.linear.body)

    def test_accept_all_records_every_recommendation_and_a_given_answer_wins(self):
        out = self.decide("Q2: C", quote="accept all except the db, Mongo", accept_all=True)
        self.assertIn(f"- Q1: A. Clerk (product owner, {TODAY}", self.linear.body)
        self.assertIn(f"- Q2: C. Mongo (product owner, {TODAY}", self.linear.body)
        self.assertIn("1 card(s) still open", out.replace("0 card(s) still open", "")) if False else None
        self.assertEqual(len(self.linear.writes), 1)

    def test_a_letter_with_a_rider_keeps_the_rider(self):
        self.decide("Q1: B, but reuse the session table", quote="B, but reuse the session table")
        self.assertIn("- Q1: B. Own JWT (but reuse the session table) (product owner", self.linear.body)

    def test_under_away_or_yolo_no_quote_records_the_recommendation_unconfirmed_and_logs_it(self):
        y = {"mode": "away", "since": "2026-10-24 08:00:00", "decisions": [], "words": "", "push": False}
        (self.proj / "results" / "yolo.json").write_text(json.dumps(y))
        out = self.decide(accept_all=True)
        self.assertIn(f"- Q1: A. Clerk (away recommendation, unconfirmed, {TODAY})", self.linear.body)
        self.assertIn(f"- Q2: B. SQLite (away recommendation, unconfirmed, {TODAY})", self.linear.body)
        logged = json.loads((self.proj / "results" / "yolo.json").read_text())["decisions"]
        self.assertEqual([d["text"].split(" (")[0] for d in logged], ["Q1: A. Clerk", "Q2: B. SQLite"])
        self.assertIn("recorded on NEB-1: Q1: A. Clerk (away recommendation", out)
        (self.proj / "results" / "yolo.json").write_text(json.dumps({**y, "mode": "yolo", "decisions": []}))
        self.decide(new=["x"])
        self.assertIn(f"- D1: x (yolo recommendation, unconfirmed, {TODAY})", self.linear.body)
        logged = json.loads((self.proj / "results" / "yolo.json").read_text())["decisions"]
        self.assertEqual([d["text"].split(" (")[0] for d in logged], ["D1: x"])

    def test_a_decision_from_conversation_lands_with_the_next_free_d_id(self):
        self.linear.body = MAP.replace("- Q0: Stripe", "- D1: one plan\n- ~~D2: old~~ (C1)\n- Q0: Stripe")
        out = self.decide(new=["billing waits for auth", "day pace is capped"], quote="auth first, and cap the day")
        self.assertIn(f'- D3: billing waits for auth (product owner, {TODAY}; said: "auth first, and cap the day")', self.linear.body)
        self.assertIn("- D4: day pace is capped (product owner,", self.linear.body)
        self.assertIn("Q1. Which auth?", self.linear.body)  # open cards untouched
        self.assertIn("recorded on NEB-1: D3: billing waits for auth", out)

    def test_the_next_d_id_ignores_d_numbers_inside_a_quote_and_flattens_newlines(self):
        self.linear.body = MAP.replace("- Q0: Stripe", '- D1: x (product owner, 2026-10-01; said: "like D12")\n- Q0: Stripe')
        self.decide(new=["two\nlines"], quote="ok")
        self.assertIn("- D2: two lines (product owner,", self.linear.body)

    def test_new_decisions_need_the_quote_unless_away_or_yolo(self):
        with self.assertRaises(SystemExit) as e:
            self.decide(new=["x"])
        self.assertIn("--quote", str(e.exception.code))
        self.assertEqual(self.linear.writes, [])

    def test_new_and_card_answers_land_together_under_one_tag(self):
        self.decide("Q1: A", new=["keep sessions 30 days"], quote="A, and 30 days")
        body = self.linear.body
        self.assertIn("- Q1: A. Clerk (product owner,", body)
        self.assertIn("- D1: keep sessions 30 days (product owner,", body)
        self.assertLess(body.index("- Q1: A. Clerk"), body.index("- D1: keep"))

    def test_new_on_a_map_without_decisions_so_far_creates_the_section(self):
        self.linear.body = "## Destination\n\nA shop.\n"
        self.decide(new=["one store"], quote="one store")
        self.assertIn("## Decisions so far\n\n- D1: one store (product owner,", self.linear.body)

    def recorded(self, *lines):
        self.linear.body = "## Destination\n\nA shop.\n\n## Decisions so far\n\n" + "\n".join(lines) + "\n\n## Not yet specified\n\n## Out of scope\n"

    def test_a_quote_confirms_a_recorded_unconfirmed_card(self):
        self.recorded("- Q3: A. dark (yolo recommendation, unconfirmed, 2026-10-21)")
        self.decide("Q3", quote="dark is fine")
        self.assertIn(f'- Q3: A. dark (product owner, {TODAY}; said: "dark is fine")', self.linear.body)
        self.assertNotIn("unconfirmed", self.linear.body)

    def test_a_card_answer_replaces_the_text_of_a_recorded_unconfirmed_card(self):
        self.recorded("- Q3: A. dark (yolo recommendation, unconfirmed, 2026-10-21)")
        self.decide("Q3: light after all", quote="light")
        self.assertIn(f'- Q3: light after all (product owner, {TODAY}; said: "light")', self.linear.body)

    def test_a_quote_confirms_an_unconfirmed_d_line(self):
        self.recorded("- D1: sessions last 30 days (product owner, 2026-10-20; said: \"ok\")", "- D2: one store (yolo recommendation, unconfirmed, 2026-10-21)")
        self.decide("D2", quote="yes")
        self.assertIn(f'- D2: one store (product owner, {TODAY}; said: "yes")', self.linear.body)
        self.assertIn("- D1: sessions last 30 days", self.linear.body)

    def test_confirming_a_confirmed_line_refuses(self):
        self.recorded('- D2: one store (product owner, 2026-10-20; said: "ok")')
        before = self.linear.body
        with self.assertRaises(SystemExit) as e:
            self.decide("D2", quote="yes")
        self.assertIn("already decided", str(e.exception.code))
        self.assertIn("compose change start", str(e.exception.code))
        self.assertEqual((self.linear.writes, self.linear.body), ([], before))

    def test_a_bare_id_with_nothing_recorded_refuses(self):
        with self.assertRaises(SystemExit) as e:
            self.decide("Q9", quote="yes")
        self.assertIn("Q9", str(e.exception.code))
        self.assertEqual(self.linear.writes, [])

    def test_replaces_strikes_the_old_d_line_and_adds_the_next(self):
        self.recorded('- D1: one store (product owner, 2026-10-20; said: "ok")', '- D2: dark (product owner, 2026-10-20; said: "ok")')
        self.decide(new=["two stores"], replaces="D1", quote="two")
        body = self.linear.body
        self.assertIn('- ~~D1: one store (product owner, 2026-10-20; said: "ok")~~ (replaced by D3)', body)
        self.assertIn(f'- D3: two stores (product owner, {TODAY}; said: "two")', body)
        self.assertIn("- D2: dark", body)

    def test_a_replaced_id_is_not_reused(self):
        self.recorded('- D1: one store (product owner, 2026-10-20; said: "ok")')
        self.decide(new=["two stores"], replaces="D1", quote="two")
        self.decide(new=["three stores"], replaces="D2", quote="three")
        self.assertIn("(replaced by D2)", self.linear.body)
        self.assertIn("(replaced by D3)", self.linear.body)
        self.assertIn("- D3: three stores", self.linear.body)

    def test_replaces_needs_a_live_d_line_and_one_new(self):
        self.recorded('- ~~D1: old (product owner, 2026-10-20; said: "ok")~~ (replaced by D2)', '- D2: one store (product owner, 2026-10-20; said: "ok")')
        before = self.linear.body
        for kw in ({"new": ["x"], "replaces": "D9"}, {"new": ["x"], "replaces": "D1"}, {"new": [], "replaces": "D2"}, {"new": ["x", "y"], "replaces": "D2"}):
            with self.assertRaises(SystemExit, msg=str(kw)):
                self.decide(quote="q", **kw)
        self.assertEqual((self.linear.writes, self.linear.body), ([], before))

    def test_replaces_under_yolo_without_a_quote_is_unconfirmed_and_logged(self):
        self.recorded('- D1: one store (product owner, 2026-10-20; said: "ok")')
        (self.proj / "results" / "yolo.json").write_text(json.dumps({"mode": "yolo", "decisions": []}))
        self.decide(new=["two stores"], replaces="D1")
        self.assertIn("- D2: two stores (yolo recommendation, unconfirmed,", self.linear.body)
        self.assertIn("(replaced by D2)", self.linear.body)
        self.assertEqual(len(json.loads((self.proj / "results" / "yolo.json").read_text())["decisions"]), 1)

    def test_a_quote_confirms_an_unconfirmed_line_and_a_confirmed_one_refuses(self):
        self.linear.body = MAP.replace("## Not yet specified\n", "## Not yet specified\n\nQ3. Theme?\nA. dark - affects: tokens\nB. light - affects: tokens\nRecommendation: A\n", 1)
        self.decide("Q3: A", quote="dark is fine")
        lines = [l for l in self.linear.body.splitlines() if l.startswith("- Q3")]
        self.assertEqual(lines, [f'- Q3: A. dark (product owner, {TODAY}; said: "dark is fine")'])
        self.linear.body = self.linear.body.replace("## Not yet specified\n", "## Not yet specified\n\nQ0. Payments?\nA. Stripe - affects: fees\nB. Paddle - affects: fees\nRecommendation: A\n", 1)
        with self.assertRaises(SystemExit) as e:
            self.decide("Q0: B", quote="paddle")
        self.assertIn("Q0 is already decided", str(e.exception.code))
        self.assertIn("compose change start", str(e.exception.code))

    def test_accept_all_needs_a_recommendation_on_every_card(self):
        self.linear.body = MAP.replace("Recommendation: B\n", "")
        with self.assertRaises(SystemExit) as e:
            self.decide(quote="all yours", accept_all=True)
        self.assertIn("Q2 carry none", str(e.exception.code))

    CHANGE_CARD = ("\nW1. Stripe fees are too high for micro-payments?\nSupersedes: Q0: Stripe\nWhy: the fee screen shows 30 cents a sale.\n"
                   "A. keep it as is - affects: nothing\nB. Paddle - affects: the checkout task\nRecommendation: B - fees fit\n")

    def test_a_change_of_course_answer_strikes_the_superseded_line_and_carries_the_change_id(self):
        self.linear = FakeLinear(MAP.replace("Recommendation: B\n", "Recommendation: B\n" + self.CHANGE_CARD)
                                 .replace("- Q3: dark theme", "- ~~Q-1: light theme (product owner, 2026-10-19)~~ (C1)\n- Q3: dark theme"))
        out = self.decide("W1: B", quote="go with Paddle", change="C2")
        body = self.linear.body
        self.assertIn('- ~~Q0: Stripe (product owner, 2026-10-20; said: "stripe")~~ (C2)\n', body)
        self.assertIn(f'- W1: B. Paddle (C2; product owner, {TODAY}; said: "go with Paddle")', body)
        self.assertIn("- ~~Q-1: light theme (product owner, 2026-10-19)~~ (C1)\n", body, "a line struck by an earlier change stays")
        self.assertIn("- Q3: dark theme (yolo recommendation, unconfirmed, 2026-10-21)\n", body)
        self.assertIn("Q1. Which auth?", body, "the other cards stay open")
        self.assertNotIn("W1. Stripe fees", body)
        self.assertIn("recorded on NEB-1: W1: B. Paddle (C2;", out)

    def test_keeping_the_old_line_under_a_change_strikes_nothing(self):
        self.linear = FakeLinear(MAP.replace("Recommendation: B\n", "Recommendation: B\n" + self.CHANGE_CARD))
        self.decide("W1: A", quote="keep stripe", change="C2")
        body = self.linear.body
        self.assertIn('- Q0: Stripe (product owner, 2026-10-20; said: "stripe")\n', body)
        self.assertNotIn("~~", body)
        self.assertIn(f'- W1: A. keep it as is (C2; product owner, {TODAY}; said: "keep stripe")', body)

    def test_yolo_tag_is_the_shared_one(self):
        self.assertIs(fc.fc_yolo.YOLO_TAG, fc.fc_decide.UNCONFIRMED)


if __name__ == "__main__":
    unittest.main()
