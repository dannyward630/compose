"""The per-project frontier spend limit: `compose budget` sets it, `hold` sends frontier
work that has reached it back to standard and reports needs-user."""
import json, math, sys, time

import fc_core, fc_tierspend

DEFAULT_LIMIT = 25.0

def check(value, where):
    """`value` as a dollar limit: a number of 0 or more. Anything else exits naming `where`, the file or command it came from."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        sys.exit(f"{where}: frontier must be a number of dollars, 0 or more, not {value!r}")
    return float(value)

def limit(proj):
    """The limit: "frontier" in results/budget.json, else DEFAULT_LIMIT when the file is missing or unreadable. A file that
    parses but holds a negative or non-numeric limit exits naming the file and key, since a guess would hold or free all spend."""
    f = proj / "results" / "budget.json"
    try:
        saved = json.loads(f.read_text())
    except (OSError, json.JSONDecodeError):
        return DEFAULT_LIMIT
    if not isinstance(saved, dict):
        sys.exit(f"{f}: must be an object such as {{\"frontier\": {DEFAULT_LIMIT:g}}}, not {saved!r}")
    return check(saved["frontier"], f) if "frontier" in saved else DEFAULT_LIMIT

def cmd_budget(a):
    proj = fc_core.project_dir(a)
    fc_core.atomic_write(proj / "results" / "budget.json", json.dumps({"frontier": check(a.dollars, "compose budget")}))
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
