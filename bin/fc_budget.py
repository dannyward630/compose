"""The per-project frontier spend limit: `compose budget` sets it, `hold` sends frontier
work that has reached it back to standard and reports needs-user."""
import json, time

import fc_core, fc_tierspend

DEFAULT_LIMIT = 25.0

def limit(proj):
    """The limit: "frontier" in results/budget.json, else DEFAULT_LIMIT when the file is missing or unreadable."""
    try:
        return float(json.loads((proj / "results" / "budget.json").read_text()).get("frontier", DEFAULT_LIMIT))
    except (OSError, json.JSONDecodeError):
        return DEFAULT_LIMIT

def cmd_budget(a):
    proj = fc_core.project_dir(a)
    fc_core.atomic_write(proj / "results" / "budget.json", json.dumps({"frontier": a.dollars}))
    print(f"frontier limit ${a.dollars:.2f} for {proj.name}")

def hold(proj, tier):
    """Frontier work whose spend has reached the limit runs at standard instead, with a needs-user report for the team lead."""
    if tier != "frontier":
        return tier
    spent, lim = fc_tierspend.frontier(proj), limit(proj)
    if spent < lim:
        return tier
    (proj / "results" / "crew").mkdir(parents=True, exist_ok=True)
    with (proj / "results" / "crew" / "frontier-budget.status").open("a") as f:
        f.write(json.dumps({"at": time.strftime("%Y-%m-%d %H:%M:%S"), "state": "needs-user",
                            "message": f"frontier spend ${spent:.2f} reached the ${lim:.2f} limit of {proj.name}: new frontier work runs at "
                                       f"standard; raise it with compose budget --project {proj.name} frontier <dollars>"}) + "\n")
    return "standard"
