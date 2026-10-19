"""The delivery plan's section text: pure, section text in and section text out; fc_linear reads and writes Linear."""

def replace_section(body, heading, text):
    text = text.strip()
    new = text.split("\n")[0] if text.startswith("## ") else heading
    section = new + "\n\n" + text.removeprefix(new).strip() if text else ""
    lines = body.split("\n")
    if heading not in lines:
        return body.rstrip("\n") + "\n\n" + section + "\n" if section else body
    i = lines.index(heading)
    end = next((j for j in range(i + 1, len(lines)) if lines[j].startswith("## ")), len(lines))
    parts = [p for p in ("\n".join(lines[:i]).rstrip("\n"), section.rstrip("\n"), "\n".join(lines[end:]).rstrip("\n")) if p]
    return "\n\n".join(parts) + "\n" if parts else ""

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
