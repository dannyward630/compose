"""Jev's route for one task: a workflow and a depth on closed choices, one retry with more context, the STANDARD
fallback, and the policy floor Jev never lowers."""

import fc_models


def route_questions(state, plain):
    """The choice questions for one task: workflow (unless pinned), depth, and one per policy without globs."""
    workflows = {"TEST_FIRST": "Write the failing test first, then make it pass.",
                 "IMPLEMENT_THEN_TEST": "Implement the task, then cover it with a test.",
                 "FIX_THEN_REGRESSION_TEST": "Fix the bug and add a test that fails without the fix."}
    depths = {"FAST": "A small, low-risk change with minimal testing.", "STANDARD": "The usual change with its tests.",
              "DEEP": "A wide or risky change with thorough testing and scrutiny."}
    applies = {"APPLIES": "This policy governs how the task is done.", "DOES_NOT_APPLY": "This policy does not govern it."}
    if state.get("check"):
        workflows["CHECK_ONLY"] = ("Small work whose result shows by running it: state the expected behavior, do the work, "
                                   "run the same check again; no written test and no suite")
    questions = {}
    if not state.get("pin"):
        questions["workflow"] = {"type": "choice", "criteria": workflows, "instructions": {"task": state.get("task", "")}}
    if state.get("pin") != "check-only" or state.get("recorded"):
        questions["depth"] = {"type": "choice", "criteria": depths, "instructions": {"task": state.get("task", "")}}
    for i, policy in enumerate(plain):
        if policy.get("globs"):
            continue
        questions[f"policy{i}"] = {"type": "choice", "criteria": applies,
                                   "instructions": {"policy": policy["name"], "statement": policy["statement"]}}
    return questions


def decide(env, cfg, state, matched, plain, more):
    """Ask Jev, retry once with {**state, "dependencies": more()}, fall back, apply the floor. Returns {"workflow", "depth",
    "decided_by", "confidence", "answers", "retry", "fallback", "floor", "checks"}."""
    questions = route_questions(state, plain)
    threshold = cfg.get("route_threshold", 0.6)
    pin = state.get("pin")

    def low(answers):
        return any(not (a := answers.get(k)) or (a.get("confidence") or 0) < threshold for k in questions)

    reply, retry, why = None, None, None
    try:
        reply = fc_models.jev_ask(env, cfg, state, questions, "Jev route") if questions else {"answers": {}}
        if questions and low(reply.get("answers", {})):
            retry = more()
            reply = fc_models.jev_ask(env, cfg, {**state, "dependencies": retry}, questions, "Jev route retry")
            if low(reply.get("answers", {})):
                why = f"confidence below {threshold}"
    except fc_models.PaymentRequired:
        raise
    except Exception as e:  # noqa: BLE001
        why = f"Jev unavailable: {e}"
    answers = (reply or {}).get("answers", {})
    confs = [a["confidence"] for a in answers.values() if a.get("confidence") is not None]
    if why:
        workflow, depth, decided_by = pin or "test-first", "STANDARD", "fallback"
    else:
        workflow = pin or answers["workflow"]["choice"].lower().replace("_", "-")
        depth = answers["depth"]["choice"] if "depth" in answers else "STANDARD"
        decided_by = None if not questions else "jev" if retry is None else "jev after retry"
    recorded = state.get("recorded")
    if workflow == "check-only" and not recorded:
        depth = "FAST"
    floor = [p["name"] for p in matched]
    checks = [c for p in matched for c in p["checks"]]
    if reply is None:
        checks += [c for p in plain for c in p["checks"]]
    else:
        for i, p in enumerate(plain):
            a = answers.get(f"policy{i}")
            if not (a and a.get("choice") == "DOES_NOT_APPLY" and (a.get("confidence") or 0) >= threshold):
                floor.append(p["name"])
                checks += p["checks"]
    checks = list(dict.fromkeys(checks))
    if floor:
        depth = "DEEP"
        if workflow == "check-only" and not recorded:
            workflow, decided_by, pin = "test-first", "floor", None
    by = "pin" if decided_by is None else f"pin + {decided_by}" if pin else decided_by
    return {"workflow": workflow, "depth": depth, "decided_by": by,
            "confidence": min(confs) if confs else None, "answers": answers, "retry": retry, "fallback": why,
            "floor": floor, "checks": checks}
