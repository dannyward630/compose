"""`compose route`: each task's workflow and depth, project policies first, Jev for the rest; recorded on the task issue
when the workspace has a Linear key, printed only without one."""
import os, sys
from pathlib import Path

import fc_config, fc_core, fc_linear, fc_policy, fc_routejev, fc_routectx, fc_routerec, fc_tasks


def route_tasks(repo, proj, tasks, recalculate=False):
    """Route each task, print one line per task, record it with a Linear key. Returns ({id: route}, {id: why held})."""
    fc_linear.linear_ready()
    try:
        policies, note = fc_policy.read_policies(repo)
    except RuntimeError as e:
        return {}, {m["id"]: str(e) for m in tasks}
    cfg = fc_core.project_config(proj)
    env = {**fc_core.load_env(cfg.get("env_file", fc_config.ENV_FILE)), **os.environ}
    plain = [p for p in policies if not p["globs"]]
    issues = fc_tasks.linear_cache(proj).get("issues", {})
    routes = {}
    for m in tasks:
        state = fc_routectx.route_context(repo, proj, m, tasks, issues)
        route = fc_routejev.decide(env, cfg, state, fc_policy.glob_matches(policies, m["files"]), plain, lambda: fc_routectx.dependency_context(repo, m))
        route["note"] = note
        route["reason"] = fc_routerec.route_reason(route, state)
        routes[m["id"]] = route
        print(f"{m['id']} {route['depth']} {route['workflow']}  {route['reason']}")
    return routes, {}


def record_route(proj, meta, section):
    """Write the section into the task issue's description, post it as a comment, and update the sync cache."""
    raise NotImplementedError("record_route")


def cmd_route(a):
    """Route the project's tasks: --only NNN[,NNN], --recalculate."""
    proj = fc_core.project_dir(a)
    repo = Path(a.repo).resolve()
    tasks = fc_tasks.code_tasks(fc_tasks.load_tasks(proj, required=True))
    if a.only:
        ids = {x.strip() for x in a.only.split(",") if x.strip()}
        tasks = [m for m in tasks if m["id"] in ids]
    if not tasks:
        line = "no tasks on Linear under this feature carry a compose block"
        sys.exit(line + (f" with ids {a.only}" if a.only else ""))
    routes, held = route_tasks(repo, proj, tasks, a.recalculate)
    if held:
        sys.exit(f"route stopped: {next(iter(held.values()))}; nothing recorded")
