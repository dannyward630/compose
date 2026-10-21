"""Verify at the stack's depth: its deepest route, the verify settings for it, and the stages it skips on the ledger."""


def stack_depth(proj, tasks):
    """(depth, task id) of the stack's deepest code task; ("STANDARD", None) with none."""
    import fc_routerec
    import fc_tasks
    issues = fc_tasks.linear_cache(proj).get("issues") or {}
    best, best_id = "STANDARD", None
    for i, m in enumerate(fc_tasks.code_tasks(tasks)):
        route = fc_routerec.parse_route((issues.get(m.get("linear")) or {}).get("description") or "")
        depth = route.get("depth") if route else None
        if depth not in fc_tasks.DEPTHS:
            depth = "STANDARD"
        if best_id is None or fc_tasks.DEPTHS.index(depth) > fc_tasks.DEPTHS.index(best):
            best, best_id = depth, m["id"]
    return best, best_id


def depth_config(cfg, proj, tasks):
    """(new cfg, depth, task id): the verify cfg at the stack's depth, `cfg` left unchanged."""
    raise NotImplementedError("depth_config")


def depth_events(cfg, run_cfg, depth, task_id, sha):
    """One `skipped` ledger event per stage `cfg` runs and `run_cfg` does not."""
    raise NotImplementedError("depth_events")


def record_depth(proj, repo, cfg, run_cfg, depth, task_id):
    """Write the skipped stages on the feature issue's ledger; add_row's answer, True with none."""
    raise NotImplementedError("record_depth")
