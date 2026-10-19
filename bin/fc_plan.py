"""The delivery plan's section text: pure, section text in and section text out; fc_linear reads and writes Linear."""

def replace_section(body, heading, text):
    raise NotImplementedError

PLAN_SECTIONS = ("## Start today", "## Lanes", "## Waves", "## Critical path", "## Outside waits", "## How this maps to compose",
                 "## Priority when something has to give")
PLAN_NEXT = "Next: the planner writes this at its cut."

def plan_skeleton():
    raise NotImplementedError

def with_plan_link(description, title, url):
    raise NotImplementedError

def start_today(lanes):
    raise NotImplementedError

def lanes_text(lanes):
    raise NotImplementedError

def waves_text(lanes):
    raise NotImplementedError

def critical_path_text(lanes):
    raise NotImplementedError

def plan_sections(lanes):
    raise NotImplementedError
