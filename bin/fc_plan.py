"""The delivery plan's section text: pure, section text in and section text out; fc_linear reads and writes Linear."""

import fc_tasks

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
    return "\n\n".join(f"{h}\n\n{PLAN_NEXT}" for h in PLAN_SECTIONS) + "\n"

def with_plan_link(description, title, url):
    if url in description:
        return description
    line = f"* Delivery plan: [{title}]({url})"
    lines = description.split("\n")
    if "## Notes" in lines:
        i = lines.index("## Notes")
        end = next((j for j in range(i + 1, len(lines)) if lines[j].startswith("## ")), len(lines))
        ins = max(j for j in range(i, end) if lines[j].strip()) + 1
        return "\n".join(lines[:ins] + [line] + lines[ins:])
    return description.rstrip("\n") + "\n\n## Notes\n\n" + line + "\n"

def start_today(lanes):
    starts = [s for l in lanes for s in l["stories"] if s["state"].lower() in {"todo", "backlog"}
              and all(fc_tasks.blocker_finished(b["state"], b["labels"]) for b in s["blockers"])]
    if not starts:
        return "Nothing can start now."
    return "\n".join(f"{n}. [{s['id']}]({s['url']}) {s['title']}" for n, s in enumerate(starts, 1))

def lanes_text(lanes):
    ids = {s["id"] for l in lanes for s in l["stories"] if s["state"].lower() != "canceled"}
    blocks = []
    for l in lanes:
        stories = [s for s in l["stories"] if s["state"].lower() != "canceled"]
        mine = {s["id"] for s in stories}
        num = lambda s: int(s["id"].rsplit("-", 1)[1])
        done, order = set(), []
        while True:
            ready = [s for s in stories if s["id"] not in done
                     and all(b["id"] in done or b["id"] not in mine for b in s["blockers"])]
            if not ready:
                break
            s = min(ready, key=num)
            done.add(s["id"])
            order.append(s)
        lines = []
        for n, s in enumerate(order + sorted((s for s in stories if s["id"] not in done), key=num), 1):
            lines.append(f"{n}. [{s['id']}]({s['url']}) {s['title']} ({s['state']})")
            needs = [b["id"] for b in s["blockers"] if b["id"] in ids and b["id"] not in mine]
            if needs:
                lines.append("   Needs: " + ", ".join(needs))
        blocks.append("\n".join([f"### [{l['id']}]({l['url']}) {l['title']}", ""] + (lines or ["No stories yet."])))
    return "\n\n".join(blocks)

def waves_text(lanes):
    stories = [s for l in lanes for s in l["stories"] if not fc_tasks.blocker_finished(s["state"], s["labels"])]
    if not stories:
        return "Nothing left to schedule."
    mine = {s["id"] for s in stories}
    num = lambda s: int(s["id"].rsplit("-", 1)[1])
    done, waves = set(), []
    while True:
        wave = sorted((s for s in stories if s["id"] not in done
                       and all(b["id"] in done or b["id"] not in mine for b in s["blockers"])), key=num)
        if not wave:
            break
        done.update(s["id"] for s in wave)
        waves.append(wave)
    rows = [f"| {n} | {', '.join(s['id'] for s in w)} | {len(w)} |" for n, w in enumerate(waves, 1)]
    return "\n".join(["| Wave | Stories | Count |", "| -- | -- | -- |"] + rows)

def critical_path_text(lanes):
    raise NotImplementedError

def plan_sections(lanes):
    return {"## Start today": start_today(lanes), "## Lanes": lanes_text(lanes), "## Waves": waves_text(lanes)}
