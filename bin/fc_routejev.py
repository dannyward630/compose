"""Jev's route for one task: a workflow and a depth on closed choices, one retry with more context, the STANDARD
fallback, and the policy floor Jev never lowers."""


def route_questions(state, plain):
    """The choice questions for one task: workflow (unless pinned), depth, and one per policy without globs."""
    raise NotImplementedError("route_questions")


def decide(env, cfg, state, matched, plain, more):
    """Ask Jev, retry once with {**state, "dependencies": more()}, fall back, apply the floor. Returns {"workflow", "depth",
    "decided_by", "confidence", "answers", "retry", "fallback", "floor", "checks"}."""
    raise NotImplementedError("decide")
