"""The route's record: the reason the CLI composes, and the CLI-owned `## Route` section of the task issue."""


def route_reason(route, state):
    """The recorded reason: Jev's answers or the fallback, the context, the Bug flags, the floor, and the policy note."""
    pin = state["pin"]
    if route["fallback"] is None:
        d = route["answers"]["depth"]
        part1 = f"Jev: depth {d['choice']} (p {d['probabilities'][d['choice']]:.2f}, confidence {d['confidence']:.2f})"
        w = route["answers"].get("workflow")
        if pin:
            part1 += f", workflow {pin} pinned"
        elif w:
            part1 += (f", workflow {w['choice'].lower().replace('_', '-')}"
                      f" (p {w['probabilities'][w['choice']]:.2f}, confidence {w['confidence']:.2f})")
        else:
            part1 += f", workflow {route['workflow']}"
    else:
        part1 = f"fallback {route['depth']} {route['workflow']}"
        if pin:
            part1 += " pinned"
        part1 += f": {route['fallback']}"
    if route["retry"] is not None:
        part1 += (" after a retry with dependency analysis" if "callers" in route["retry"]
                  else " after a retry, dependency analysis unavailable")
    files = state["files"]
    tops = []
    for f in files:
        top = f["path"].split("/")[0]
        if top not in tops:
            tops.append(top)
    new = sum(1 for f in files if not f["exists"])
    shared = len({f["path"] for f in files} & set(state["other_files"]))
    n, c = len(files), len(state["criteria"])
    part2 = f"{n} file{'s' if n != 1 else ''}"
    if tops:
        part2 += f" under {', '.join(tops)}"
    part2 += f" ({new} new), {c} criteri{'on' if c == 1 else 'a'}, {shared} shared with other open tasks"
    bug = state["bug"]
    if bug["label"]:
        part3 = (f"Bug label, reproduction {'documented' if bug['documented'] else 'not documented'},"
                 f" {'confirmed' if bug['confirmed'] else 'not confirmed'}")
    else:
        part3 = "no Bug label"
    parts = [part1, part2, part3]
    if route["floor"]:
        parts.append(f"floor DEEP from {', '.join(route['floor'])}")
    if route.get("note"):
        parts.append(route["note"])
    return "; ".join(parts)


def route_section(route):
    """The `## Route` section text for one route."""
    raise NotImplementedError("route_section")


def parse_route(desc):
    """The Route section's bullets keyed by their labels; None without the section."""
    raise NotImplementedError("parse_route")


def with_route(desc, section):
    """`desc` with its Route section replaced in place, else inserted right above the compose block."""
    raise NotImplementedError("with_route")
