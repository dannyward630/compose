import hermetic  # first: no test sees the real home
import importlib.machinery, importlib.util, io, json, os, sys, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
os.environ["HERDR_ENV"] = ""

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)
import fc_plan  # noqa: E402  # compose.py puts bin on sys.path; nothing imports fc_plan before 007


def story(ident, state="Todo", *blockers, labels=()):
    return {"id": ident, "title": "T " + ident, "url": "u/" + ident, "state": state, "labels": list(labels),
            "blockers": [{"id": b[0], "state": b[1], "labels": list(b[2]) if len(b) > 2 else []} for b in blockers]}

def lane(ident, *stories):
    return {"id": ident, "title": "L " + ident, "url": "u/" + ident, "stories": list(stories)}


class StartToday(unittest.TestCase):
    LINK = "* Delivery plan: [NEB-1: delivery plan](https://linear.app/x/document/d1)"

    def test_skeleton_holds_the_seven_sections_in_order_each_with_the_next_line(self):
        self.assertEqual(fc_plan.plan_skeleton(), "\n\n".join(f"{h}\n\n{fc_plan.PLAN_NEXT}" for h in fc_plan.PLAN_SECTIONS) + "\n")

    def link(self, description):
        return fc_plan.with_plan_link(description, "NEB-1: delivery plan", "https://linear.app/x/document/d1")

    def test_link_goes_last_in_notes_before_the_next_section(self):
        lines = self.link("## Goal\n\nShip it.\n\n## Notes\n\n* old note\n\n## Constraints\n\n* none\n").splitlines()
        self.assertEqual(lines.count(self.LINK), 1)
        i = lines.index(self.LINK)
        self.assertLess(lines.index("* old note"), i)
        self.assertEqual([l for l in lines[i + 1:] if l.strip()], ["## Constraints", "* none"])
        self.assertEqual([l for l in lines[:i] if l.strip()], ["## Goal", "Ship it.", "## Notes", "* old note"])

    def test_link_ends_a_last_notes_section_or_adds_one_and_is_never_added_twice(self):
        lines = self.link("## Goal\n\nShip it.\n\n## Notes\n\n* old note\n").splitlines()
        self.assertEqual([l for l in lines if l.strip()], ["## Goal", "Ship it.", "## Notes", "* old note", self.LINK])
        lines = self.link("## Goal\n\nShip it.\n").splitlines()
        self.assertEqual([l for l in lines if l.strip()], ["## Goal", "Ship it.", "## Notes", self.LINK])
        linked = "## Notes\n\n" + self.LINK + "\n"
        self.assertEqual(self.link(linked), linked)
        self.assertEqual(self.link(self.link("## Goal\n\nShip it.\n")).splitlines().count(self.LINK), 1)

    def test_start_today_lists_todo_or_backlog_stories_whose_blockers_are_finished(self):
        lanes = [lane("NEB-1", story("NEB-3"), story("NEB-4", "Todo", ("NEB-3", "Todo")), story("NEB-5", "Todo", ("NEB-9", "In Review", ["Design"])),
                      story("NEB-6", "In Progress"), story("NEB-7", "Done"), story("NEB-8", "Todo", ("NEB-20", "In Review"))),
                 lane("NEB-2", story("NEB-12", "backlog", ("NEB-21", "Done"), ("NEB-22", "Canceled")), story("NEB-13", "Backlog", ("NEB-21", "Done"), ("NEB-23", "In Progress")))]
        self.assertEqual(fc_plan.start_today(lanes).splitlines(), ["1. [NEB-3](u/NEB-3) T NEB-3", "2. [NEB-5](u/NEB-5) T NEB-5", "3. [NEB-12](u/NEB-12) T NEB-12"])
        self.assertEqual(fc_plan.plan_sections(lanes)["## Start today"], fc_plan.start_today(lanes))

    def test_nothing_to_start(self):
        for lanes in ([], [lane("NEB-1")], [lane("NEB-1", story("NEB-3", "Done"), story("NEB-4", "Todo", ("NEB-3", "In Review")))]):
            self.assertEqual(fc_plan.start_today(lanes).strip(), "Nothing can start now.")
            self.assertEqual(fc_plan.plan_sections(lanes)["## Start today"], fc_plan.start_today(lanes))



class PlanLanes(unittest.TestCase):
    def lines(self, lanes):
        return fc_plan.lanes_text(lanes).strip("\n").split("\n")

    def test_lanes_in_order_with_stories_in_build_order_and_needs_lines(self):
        lanes = [lane("NEB-1", story("NEB-12", "Todo", ("NEB-5", "Todo")), story("NEB-10"), story("NEB-7", "canceled"),
                      story("NEB-5", "In Progress", ("NEB-31", "Todo"), ("NEB-99", "Todo"), ("NEB-30", "Done")), story("NEB-9", "Todo", ("NEB-10", "Todo"))),
                 lane("NEB-2", story("NEB-31", "Todo", ("NEB-30", "Done")), story("NEB-30", "Done")),
                 lane("NEB-3")]
        self.assertEqual(self.lines(lanes), [
            "### [NEB-1](u/NEB-1) L NEB-1", "",
            "1. [NEB-5](u/NEB-5) T NEB-5 (In Progress)", "   Needs: NEB-31, NEB-30",
            "2. [NEB-10](u/NEB-10) T NEB-10 (Todo)", "3. [NEB-9](u/NEB-9) T NEB-9 (Todo)", "4. [NEB-12](u/NEB-12) T NEB-12 (Todo)", "",
            "### [NEB-2](u/NEB-2) L NEB-2", "",
            "1. [NEB-30](u/NEB-30) T NEB-30 (Done)", "2. [NEB-31](u/NEB-31) T NEB-31 (Todo)", "",
            "### [NEB-3](u/NEB-3) L NEB-3", "", "No stories yet."])
        self.assertEqual(list(fc_plan.plan_sections(lanes))[:2], ["## Start today", "## Lanes"])
        self.assertEqual(fc_plan.plan_sections(lanes)["## Lanes"], fc_plan.lanes_text(lanes))

    def test_stories_caught_in_a_cycle_follow_by_issue_number(self):
        lanes = [lane("NEB-4", story("NEB-41", "Todo", ("NEB-40", "Todo")), story("NEB-40", "Todo", ("NEB-41", "Todo")),
                      story("NEB-43", "Todo", ("NEB-45", "Todo")), story("NEB-45", "Backlog"), story("NEB-44", "CANCELED"))]
        self.assertEqual(self.lines(lanes), [
            "### [NEB-4](u/NEB-4) L NEB-4", "",
            "1. [NEB-45](u/NEB-45) T NEB-45 (Backlog)", "2. [NEB-43](u/NEB-43) T NEB-43 (Todo)",
            "3. [NEB-40](u/NEB-40) T NEB-40 (Todo)", "4. [NEB-41](u/NEB-41) T NEB-41 (Todo)"])
