"""The FAST route (fix-then-regression-test): its holds before a run, its green-base check, and its run's ledger events."""


def workflow(proj, meta):
    """The task's routed workflow from its issue description in the sync cache; None without a route."""
    import fc_routerec, fc_tasks
    issue = fc_tasks.linear_cache(proj).get("issues", {}).get(meta.get("linear"))
    if not issue:
        return None
    route = fc_routerec.parse_route(issue.get("description") or "")
    return route["workflow"] if route else None


def run_holds(repo, proj, tasks, routes):
    """{id: why} for each FAST task with no expected behavior; prints that an implement-then-test task runs as test-first."""
    import fc_core, fc_tasks, fc_routectx
    held = {}
    for meta in tasks:
        route = routes.get(meta["id"])
        if not route:
            continue
        if route["workflow"] == "implement-then-test":
            fc_core.say(f"{meta['id']} route   implement-then-test is not implemented yet: it runs as test-first")
        elif route["workflow"] == "fix-then-regression-test":
            c = fc_routectx.route_context(repo, proj, meta, tasks, fc_tasks.linear_cache(proj)["issues"])
            if not c["criteria"] and not c["bug"]["documented"] and not c["bug"]["confirmed"]:
                held[meta["id"]] = "no expected behavior: add a Reproduction section or acceptance criteria"
    return held


def broken_base(proj, meta, red, base_name, branch, wt):
    """The `broken_base` result of a FAST task whose test fails on the base before any change."""
    raise NotImplementedError("broken_base")


def run_events(proj, repo, meta, result):
    """The task's run events for the ledger: a FAST task's carry no `red` event and end `unproven` when it is."""
    raise NotImplementedError("run_events")
