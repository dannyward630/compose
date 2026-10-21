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
    questions = {}
    if not state.get("pin"):
        questions["workflow"] = {"type": "choice", "criteria": workflows, "instructions": {"task": state.get("task", "")}}
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
        reply = fc_models.jev_ask(env, cfg, state, questions, "Jev route")
        if low(reply.get("answers", {})):
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
        depth, decided_by = answers["depth"]["choice"], "jev" if retry is None else "jev after retry"
    return {"workflow": workflow, "depth": depth, "decided_by": f"pin + {decided_by}" if pin else decided_by,
            "confidence": min(confs) if confs else None, "answers": answers, "retry": retry, "fallback": why,
            "floor": [], "checks": []}
