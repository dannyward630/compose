"""The delivery plan's section text: pure, section text in and section text out; fc_linear reads and writes Linear."""

import hashlib
import re

import fc_tasks

def heading_level(line):
    """2 for `## Notes`: the count of leading #s when a space follows them, else 0 (not a heading)."""
    n = len(line) - len(line.lstrip("#"))
    return n if 0 < n <= 6 and line[n:n + 1] == " " else 0

def headings(lines):
    """(index, level) of each heading line outside fenced code, where a `# comment` line is code, not a heading."""
    fence = False
    for i, line in enumerate(lines):
        if line.lstrip().startswith(("```", "~~~")):
            fence = not fence
        elif not fence and heading_level(line):
            yield i, heading_level(line)

def section_span(lines, heading):
    """The section's lines as (start, end): from its heading to the next heading of the same or a higher level, so an H2
    takes its H3s and an H3 leaves its siblings alone. None when the heading is not there."""
    marks = list(headings(lines))
    start = next((i for i, _ in marks if lines[i] == heading), None)
    if start is None:
        return None
    return start, next((i for i, n in marks if i > start and n <= heading_level(heading)), len(lines))

def section_hash(body, heading):
    """A short hash of the section as it stands, subsections included; None when it is not there. A writer passes the hash it
    read to `--expect`, and the write refuses when the section changed since."""
    lines = body.split("\n")
    span = section_span(lines, heading)
    return hashlib.sha256("\n".join(lines[span[0]:span[1]]).strip().encode()).hexdigest()[:8] if span else None

def section_hashes(body):
    """(heading, hash) for each heading, first occurrence only: the one a section write finds."""
    lines = body.split("\n")
    names = list(dict.fromkeys(lines[i] for i, _ in headings(lines)))
    return [(h, section_hash(body, h)) for h in names]

def replace_section(body, heading, text):
    text = text.strip()
    first = text.split("\n")[0]
    new = first if heading_level(first) == heading_level(heading) else heading
    section = new + "\n\n" + text.removeprefix(new).strip() if text else ""
    lines = body.split("\n")
    span = section_span(lines, heading)
    if not span:
        return body.rstrip("\n") + "\n\n" + section + "\n" if section else body
    i, end = span
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
    if span := section_span(lines, "## Notes"):
        i, end = span
        sub = next((j for j, _ in headings(lines) if i < j < end), end)
        own = [j for j in range(i + 1, sub) if lines[j].strip()]
        if own:
            ins = own[-1] + 1
            return "\n".join(lines[:ins] + [line] + lines[ins:])
        j = next((k for k in range(i + 1, end) if lines[k].strip()), end)
        return "\n".join(lines[:i + 1] + ["", line, ""] + lines[j:])
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
    stories = [s for l in lanes for s in l["stories"] if not fc_tasks.blocker_finished(s["state"], s["labels"])]
    if not stories:
        return "Nothing left to schedule."
    mine = {s["id"] for s in stories}
    num = lambda i: int(i.rsplit("-", 1)[1])
    after = {s["id"]: {b["id"] for b in s["blockers"] if b["id"] in mine} for s in stories}
    blocks = {i: sorted((j for j in mine if i in after[j]), key=num) for i in mine}
    chains = []
    def walk(i, path):
        for j in blocks[i]:
            if j not in path:
                walk(j, path + [j])
        if not blocks[i]:
            chains.append(path)
    for i in sorted((i for i in mine if not after[i]), key=num):
        walk(i, [i])
    best = max(map(len, chains), default=0)
    if best < 2:
        return "No blocked-by chains."
    return "\n".join(f"{n}. {' -> '.join(c)} ({len(c)} stories)"
                     for n, c in enumerate((c for c in chains if len(c) == best), 1))

def plan_sections(lanes):
    return {"## Start today": start_today(lanes), "## Lanes": lanes_text(lanes), "## Waves": waves_text(lanes),
            "## Critical path": critical_path_text(lanes)}


PRODUCT_NEXT = "Next: written with the product owner, then kept in step by compose delivery reconcile."
TRACK_LINE = re.compile(r"^\d+\.\s+(?P<name>[^:]+?):\s+(?P<ids>.+?)(?:\s+\(after\s+(?P<after>[^)]+)\))?\s*$")
TRACK_ID = re.compile(r"^[A-Z][A-Z0-9]*-\d+$")

def split_entries(raw):
    """Comma separated entries, each `[X](url)` link reduced to X."""
    return [re.sub(r"^\[([^\]]*)\]\(.*\)$", r"\1", e.strip()) for e in raw.split(",")]

def parse_tracks(text):
    """The `## Tracks` body as [{"rank", "name", "items", "after"}] in list order; ValueError names the offending line."""
    tracks, lines = [], []
    seen_items, seen_names = {}, {}
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.strip() == PRODUCT_NEXT:
            continue
        m = TRACK_LINE.match(line.strip())
        items = split_entries(m.group("ids")) if m else []
        if not m or not all(TRACK_ID.match(i) for i in items):
            raise ValueError('line %d: not a track: "%s" (write "<n>. <name>: <id>, <id> (after <track>, ...)")' % (n, line.strip()))
        name = m.group("name").strip()
        if name.lower() in seen_names:
            raise ValueError("line %d: a second track named %s" % (n, name))
        for i in items:
            if i in seen_items:
                raise ValueError("line %d: %s names %s, already in track %s" % (n, name, i, seen_items[i]))
        seen_names[name.lower()] = len(tracks)
        seen_items.update({i: name for i in items})
        after = split_entries(m.group("after")) if m.group("after") else []
        tracks.append({"rank": int(line.strip().split(".")[0]), "name": name, "items": items, "after": after})
        lines.append(n)
    for t, n in zip(tracks, lines):
        for a in t["after"]:
            if TRACK_ID.match(a):
                if a not in seen_items:
                    raise ValueError("line %d: %s comes after %s, which no track names" % (n, t["name"], a))
                target = seen_items[a]
            elif a.lower() in seen_names:
                target = tracks[seen_names[a.lower()]]["name"]
            else:
                raise ValueError("line %d: %s comes after %s, which is no track here" % (n, t["name"], a))
            if target.lower() == t["name"].lower():
                raise ValueError("line %d: %s comes after itself" % (n, t["name"]))
    deps = track_deps(tracks)
    state, stack = {}, []
    def walk(i):
        state[i] = 1
        stack.append(i)
        for d in deps[i]:
            if state.get(d) == 1:
                cycle = stack[stack.index(d):] + [d]
                raise ValueError("the tracks wait on each other in a loop: " + " -> ".join(tracks[c]["name"] for c in cycle))
            if d not in state:
                walk(d)
        stack.pop()
        state[i] = 2
    for i in range(len(tracks)):
        if i not in state:
            walk(i)
    return tracks

def track_deps(tracks):
    """For each track index, the sorted indexes of the tracks it comes after."""
    by_name = {t["name"].lower(): i for i, t in enumerate(tracks)}
    by_item = {x: i for i, t in enumerate(tracks) for x in t["items"]}
    return [sorted({by_item[a] if TRACK_ID.match(a) else by_name[a.lower()] for a in t["after"]}) for t in tracks]

def track_waves(tracks):
    """Tracks grouped into waves: a track with nothing before it is in wave 1, any other one wave after its latest predecessor."""
    deps, depth = track_deps(tracks), {}
    def level(i):
        if i not in depth:
            depth[i] = 1 + max((level(d) for d in deps[i]), default=-1)
        return depth[i]
    waves = {}
    for i, t in enumerate(tracks):
        waves.setdefault(level(i), []).append(t)
    return [waves[k] for k in sorted(waves)]

def derived_blocks(tracks):
    """{(blocker, blocked)}: each item blocks the next in its track; an `after` track's last item, or the `after` id, blocks this track's first."""
    by_name = {t["name"].lower(): t for t in tracks}
    out = set()
    for t in tracks:
        out.update(zip(t["items"], t["items"][1:]))
        for a in t["after"]:
            out.add((a if TRACK_ID.match(a) else by_name[a.lower()]["items"][-1], t["items"][0]))
    return out

def blocks_diff(derived, current, plan_ids):
    """(added, removed) relations to reach `derived`; `current` maps a blocked id to its blocker ids, and only pairs between plan_ids count."""
    now = {(b, k) for k, bs in current.items() for b in bs if b in plan_ids and k in plan_ids}
    def order(pair):
        return (int(pair[1].rsplit("-", 1)[1]), int(pair[0].rsplit("-", 1)[1]))
    return sorted(derived - now, key=order), sorted(now - derived, key=order)

def base_built(state, labels):
    """A base feature is built once it is finished, or In Review (verified)."""
    return fc_tasks.blocker_finished(state, labels) or state.lower() == "in review"
