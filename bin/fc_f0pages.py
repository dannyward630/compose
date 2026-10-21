import copy, json, os, re, shutil, sys, time
from pathlib import Path
import fc_core, fc_frame0

# ---------- frame0 pages, move, delete, links, lint: structure in one command ----------

# design.f0 is plain JSON: a Doc whose children are the Page nodes in page order, each page a tree of shapes. A shape that links to
# a page keeps that page's id in `reference` (a web link is `link`). Frame0's API reaches the same things one call at a time
# (page:move, page:delete, shape:set-link), which is hundreds of agent turns for a reorder, a link fix, and a pile of deletions.
# So a change is a short list of ops planned on the saved file, run over the API when the project's app is up (the app owns the file
# and would write over an edit made behind its back, and a restart would cost an Allow click) or as a JSON edit when it is closed,
# and then read back from the file: a drawing that does not end up as planned is reported with its backup.
FRAME0_BACKUPS = 5  # design.f0.bak-* kept next to the file
FRAME0_FLOW = re.compile(r"\s*(\d+)(?:\.(\d+))?")  # the flow number a page name starts with: "05 Today - flow", "05.3 Evidence", "05.3b"
FRAME0_LIST = 20  # most names a message spells out
FRAME0_PRINT = 30  # most changes a command prints

def frame0_load(proj):
    """The saved drawing as (doc, whether the app is running), asking a running app to save first. Raises RuntimeError."""
    running = fc_frame0.frame0_save(proj)
    design = proj / "design.f0"
    try:
        return json.loads(design.read_text(encoding="utf-8")), running
    except OSError as e:
        raise RuntimeError(f"cannot read {design} ({e}); `frame0 up` makes it") from e
    except ValueError as e:
        raise RuntimeError(f"{design} is not JSON: {e}") from e

def frame0_shapes(node):
    """Every shape under a node, a parent before its children."""
    for child in node.get("children") or []:
        yield child
        yield from frame0_shapes(child)

def frame0_pages(doc):
    """The pages in order: {n, id, name, shapes}."""
    return [{"n": n, "id": p["id"], "name": p.get("name", ""), "shapes": sum(1 for _ in frame0_shapes(p))} for n, p in enumerate(doc.get("children") or [], 1)]

def frame0_page_ref(doc, ref):
    """The page a command names: its id, its name, or an unambiguous start of its name. Raises ValueError."""
    pages = frame0_pages(doc)
    for same in (lambda p: p["id"] == ref, lambda p: p["name"] == ref, lambda p: p["name"].lower() == ref.lower(), lambda p: p["name"].lower().startswith(ref.lower())):
        found = [p for p in pages if same(p)]
        if len(found) == 1:
            return found[0]
        if found:
            raise ValueError(f"{ref!r} names {len(found)} pages ({', '.join(repr(p['name']) for p in found[:5])}); use a page id from `frame0 pages`")
    raise ValueError(f"no page {ref!r}; `frame0 pages` lists them")

def frame0_links(doc):
    """Every shape that links to a page: {shape, name, on, target, ok}, `ok` when the target page exists. A `reference` holding
    another shape's id is no page link."""
    pages = {p["id"] for p in doc.get("children") or []}
    ids = {s["id"] for s in frame0_shapes(doc)}
    return [{"shape": s["id"], "name": s.get("name", ""), "on": page["id"], "target": t, "ok": t in pages}
            for page in doc.get("children") or [] for s in frame0_shapes(page)
            if isinstance(t := s.get("reference"), str) and t and (t in pages or t not in ids)]

def frame0_misplaced(pages):
    """The numbered pages out of flow order: [(page, the page it belongs behind, or None for the front)]. A name starts with its flow
    number ("05.3 ..."), and the flows run in number order, so the pages kept in place are the longest run that never steps back, and
    every other numbered page is misplaced (one page out of place is one finding, not one for every page it jumped over). Pages with
    no number, like a journey overview, keep their place."""
    numbered = [(p, (int(m[1]), int(m[2] or 0))) for p in pages if (m := FRAME0_FLOW.match(p["name"]))]
    best = []  # best[i]: the longest run ending at numbered[i], as indexes
    for i, (_, key) in enumerate(numbered):
        run = max((best[j] for j in range(i) if numbered[j][1] <= key), key=len, default=[])
        best.append(run + [i])
    keep = set(max(best, key=len, default=[]))
    out = []
    for i, (p, key) in enumerate(numbered):
        if i not in keep:
            behind = [(k, j) for j, (_, k) in enumerate(numbered) if j in keep and k <= key]
            out.append((p, numbered[max(behind)[1]][0] if behind else None))
    return out

def frame0_dangling(doc):
    """One message for each deleted page that links still point at."""
    names = {p["id"]: p["name"] for p in frame0_pages(doc)}
    gone = {}
    for link in frame0_links(doc):
        if not link["ok"]:
            gone.setdefault(link["target"], []).append(link)
    out = []
    for target, links in list(gone.items())[:FRAME0_LIST]:
        on = sorted({names[link["on"]] for link in links})
        out.append(f"{len(links)} links to a page that is gone ({target}), on {', '.join(map(repr, on[:3]))}{f' and {len(on) - 3} more pages' if len(on) > 3 else ''}: "
                   f"`compose frame0 links --retarget {target}=<page>` or `compose frame0 links --drop-dangling`")
    if len(gone) > FRAME0_LIST:
        out.append(f"and links to {len(gone) - FRAME0_LIST} more pages that are gone")
    return out

def frame0_lint(doc):
    """What the designer fixes before asking for a review: empty pages, pages out of flow order, links to deleted pages.
    Returns the problems, one message each."""
    pages, problems = frame0_pages(doc), []
    empty = [p for p in pages if not p["shapes"]]
    if empty:
        listed = ", ".join(f"{p['n']} {p['name']!r}" for p in empty[:FRAME0_LIST]) + (f", and {len(empty) - FRAME0_LIST} more" if len(empty) > FRAME0_LIST else "")
        problems.append(f"{len(empty)} empty pages: {listed}; draw them or delete them with `compose frame0 delete --empty`")
    misplaced = frame0_misplaced([p for p in pages if p["shapes"]])  # an empty page is already reported
    for p, behind in misplaced[:FRAME0_LIST]:
        fix = f"`compose frame0 move --page {p['id']} --after {behind['id']}`" if behind else f"`compose frame0 move --page {p['id']} --first`"
        problems.append(f"page {p['n']} {p['name']!r} is out of flow order; it belongs {'behind ' + repr(behind['name']) if behind else 'first'}: {fix}")
    if len(misplaced) > FRAME0_LIST:
        problems.append(f"and {len(misplaced) - FRAME0_LIST} more pages out of flow order")
    return problems + frame0_dangling(doc)

def frame0_plan_move(doc, refs, after):
    """Ops moving the named pages, in the order given, behind `after` (None: to the front). Only a page that changes place gets an op."""
    moving = list(dict.fromkeys(frame0_page_ref(doc, r)["id"] for r in refs))
    order = [p["id"] for p in frame0_pages(doc)]
    anchor = None if after is None else frame0_page_ref(doc, after)["id"]
    if anchor in moving:
        raise ValueError("--after names a page that is being moved")
    ops = []
    for pid in moving:
        before = order.index(pid)
        order.remove(pid)
        at = order.index(anchor) + 1 if anchor else 0
        order.insert(at, pid)
        if at != before:
            ops.append(("move", pid, at))
        anchor = pid
    return ops

def frame0_plan_delete(doc, refs, empty):
    """Ops deleting the named pages and, with `empty`, every page without a shape. A link to a deleted page is cleared with it."""
    pages = frame0_pages(doc)
    gone = list(dict.fromkeys([frame0_page_ref(doc, r)["id"] for r in refs] + [p["id"] for p in pages if empty and not p["shapes"]]))
    if len(gone) >= len(pages):
        raise ValueError("a drawing keeps at least one page")
    return [("unlink", link["shape"]) for link in frame0_links(doc) if link["target"] in gone and link["on"] not in gone] + [("delete", i) for i in gone]

def frame0_plan_links(doc, retarget, drop):
    """Ops pointing the links to a page (or to a deleted page's id) at another page, and with `drop` clearing links to deleted pages."""
    moves = {}
    for pair in retarget:
        old, _, new = pair.partition("=")
        if not new:
            raise ValueError(f"--retarget is <old page or id>=<new page>, not {pair!r}")
        try:
            old = frame0_page_ref(doc, old)["id"]
        except ValueError:  # the id of a page that is gone
            pass
        moves[old] = frame0_page_ref(doc, new)["id"]
    links = frame0_links(doc)
    for old in moves:
        if not any(link["target"] == old for link in links):
            raise ValueError(f"no link points at {old}")
    return [("relink", link["shape"], moves[link["target"]]) for link in links if link["target"] in moves and moves[link["target"]] != link["target"]] + \
           [("unlink", link["shape"]) for link in links if drop and not link["ok"] and link["target"] not in moves]

def frame0_describe(doc, op):
    """One line saying what an op does."""
    pages = frame0_pages(doc)
    names = {p["id"]: p["name"] for p in pages}
    if op[0] == "move":
        return f"move {names[op[1]]!r} to position {op[2] + 1}"
    if op[0] == "delete":
        return f"delete {names[op[1]]!r} ({next(p['shapes'] for p in pages if p['id'] == op[1])} shapes)"
    link = next(link for link in frame0_links(doc) if link["shape"] == op[1])
    if op[0] == "relink":
        return f"point {link['name']!r} on {names[link['on']]!r} at {names[op[2]]!r}"
    return f"clear the link of {link['name']!r} on {names[link['on']]!r} (it pointed at {repr(names[link['target']]) if link['target'] in names else 'a page that is gone'})"

def frame0_apply_json(doc, ops):
    """Run the ops on a loaded drawing."""
    pages = doc["children"]
    by_id = {p["id"]: p for p in pages}
    shapes = {s["id"]: s for p in pages for s in frame0_shapes(p)}
    for op in ops:
        if op[0] == "move":
            pages.insert(op[2], pages.pop(pages.index(by_id[op[1]])))
        elif op[0] == "delete":
            pages.remove(by_id.pop(op[1]))
        elif op[0] == "unlink":
            shapes[op[1]].pop("reference", None)
        else:
            shapes[op[1]]["reference"] = op[2]

def frame0_apply_api(call, ops):
    """Run the ops on the running app, one API command each. Raises RuntimeError naming the op that failed."""
    for n, op in enumerate(ops, 1):
        try:
            if op[0] == "move":
                call("page:move", {"pageId": op[1], "position": op[2]})
            elif op[0] == "delete":
                call("page:delete", {"pageId": op[1]})
            else:
                call("shape:set-link", {"shapeId": op[1], "linkProps": {"linkType": "none"} if op[0] == "unlink" else {"linkType": "page", "pageId": op[2]}})
        except RuntimeError as e:
            raise RuntimeError(f"op {n} of {len(ops)} ({op[0]}) failed: {e}") from e

def frame0_backup(design):
    """Copy design.f0 beside itself before a change, keeping the newest FRAME0_BACKUPS. Returns the copy."""
    stamp, n = time.strftime("%Y%m%d-%H%M%S"), 1
    bak = design.with_name(f"{design.name}.bak-{stamp}")
    while bak.exists():
        n += 1
        bak = design.with_name(f"{design.name}.bak-{stamp}-{n}")
    shutil.copy2(design, bak)
    for old in sorted(design.parent.glob(f"{design.name}.bak-*"), key=lambda f: f.stat().st_mtime)[:-FRAME0_BACKUPS]:
        old.unlink()
    return bak

def frame0_edit(proj, plan, dry_run=False):
    """Plan a change on the saved drawing, back the file up, run it, and check the saved file is what the plan makes. `plan(doc)`
    returns the ops (ValueError: the command is wrong). Returns the lines to print. Raises RuntimeError."""
    doc, running = frame0_load(proj)
    try:
        ops = plan(doc)
    except ValueError as e:
        raise RuntimeError(str(e)) from e
    lines = [frame0_describe(doc, op) for op in ops]
    if not ops or dry_run:
        return [*lines, "nothing to change" if not ops else "dry run: nothing changed"]
    design = proj / "design.f0"
    bak = frame0_backup(design)
    expected = copy.deepcopy(doc)
    frame0_apply_json(expected, ops)
    if running:
        call = fc_frame0.frame0_client(fc_frame0.frame0_port(proj))
        try:
            frame0_apply_api(call, ops)
        finally:
            try:
                call("file:save", {"allowSaveAs": False})
            except RuntimeError:
                pass
        now = json.loads(design.read_text(encoding="utf-8"))
        if [p["id"] for p in now["children"]] != [p["id"] for p in expected["children"]] or sorted(map(str, frame0_links(now))) != sorted(map(str, frame0_links(expected))):
            raise RuntimeError(f"Frame0 saved a drawing that is not what the plan makes; the file before is {bak}")
    else:
        tmp = design.with_name(f".{design.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(expected, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, design)  # a reader sees the old file or the new one
    return [*lines, f"{len(ops)} changes, saved {design}; the file before is {bak}"]

def frame0_table(pages, only_empty=False):
    """The `frame0 pages` listing."""
    rows = [f"{p['n']:>4} {p['id']:<21} {'empty' if not p['shapes'] else p['shapes']:>6}  {p['name']}" for p in pages if p["shapes"] == 0 or not only_empty]
    return [f"{'n':>4} {'id':<21} {'shapes':>6}  name", *rows]


def cmd_frame0_pages(a):
    """`frame0 pages` lists the pages, `move` and `delete` reorder and remove them, `links` checks the links between them and
    `--retarget`s or `--drop-dangling`s them, `lint` is the check before a review ask. Any other action is fc_frame0's."""
    if a.action in ("up", "draw", "save", "down"):
        return fc_frame0.cmd_frame0(a)
    proj = fc_core.project_dir(a)
    try:
        if a.action in ("pages", "lint", "links") and not (a.action == "links" and (a.retarget or a.drop_dangling)):
            doc, _ = frame0_load(proj)
            if a.action == "pages":
                pages = frame0_pages(doc)
                print("\n".join(frame0_table(pages, a.empty)))
                print(f"{len(pages)} pages, {sum(not p['shapes'] for p in pages)} empty")
            elif a.action == "lint":
                problems = frame0_lint(doc)
                if problems:
                    sys.exit("frame0 lint: fix these before asking for a review\n" + "\n".join(problems))
                print(f"frame0 lint: {len(frame0_pages(doc))} pages, none empty, in flow order, every link lands on a page")
            else:
                links = frame0_links(doc)
                problems = frame0_dangling(doc)
                print(f"{len(links)} links to pages, {sum(not link['ok'] for link in links)} to a page that is gone")
                if problems:
                    sys.exit("\n".join(problems))
        else:
            if a.action == "move":
                if not a.page or bool(a.after) == bool(a.first):
                    sys.exit("frame0 move: --page <page> (repeatable) and one of --after <page> or --first")
                plan = lambda doc: frame0_plan_move(doc, a.page, a.after)
            elif a.action == "delete":
                if not (a.page or a.empty):
                    sys.exit("frame0 delete: --page <page> (repeatable) or --empty")
                plan = lambda doc: frame0_plan_delete(doc, a.page or [], a.empty)
            else:
                plan = lambda doc: frame0_plan_links(doc, a.retarget or [], a.drop_dangling)
            lines = frame0_edit(proj, plan, a.dry_run)
            shown = lines[:FRAME0_PRINT] if len(lines) > FRAME0_PRINT + 1 else lines[:-1]
            print("\n".join([*shown, *([f"... and {len(lines) - 1 - len(shown)} more"] if len(lines) - 1 > len(shown) else []), lines[-1]]))
    except RuntimeError as e:
        sys.exit(f"frame0 {a.action}: {e}")
