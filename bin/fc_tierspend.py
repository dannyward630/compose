"""Spend per tier, in real dollars and in Claude Code's reference dollars at list prices."""
import json

import fc_config, fc_cost, fc_tiers


def ref_dollars(model, input, cache_created, cache_read, output):
    """The list price of one call in dollars: (input, output) or (input, output, cache write, cache read) per million
    tokens, a two-number price charging cache tokens at its input price; None when the model has no price."""
    price = fc_config.PRICES.get(model) or fc_config.PRICES.get("claude:" + model)
    if price is None:
        return None
    if len(price) == 2:
        return ((input + cache_created + cache_read) * price[0] + output * price[1]) / 1e6
    return (input * price[0] + output * price[1] + cache_created * price[2] + cache_read * price[3]) / 1e6

def spend(proj):
    """{tier: {"real": real dollars, "ref": reference dollars, "unpriced": a call had no price}} for every tier."""
    out = {t: {"real": 0.0, "ref": 0.0, "unpriced": False} for t in fc_tiers.ORDER}
    for r in fc_cost.rows(proj):
        tier = fc_tiers.tier_of(r["model"])
        if not tier or r["role"] == "run" or r["input"] is None:
            continue
        price = ref_dollars(r["model"], r["input"], r["cache_created"], r["cache_read"], r["output"])
        cell = out[tier]
        if price is None:
            cell["unpriced"] = True
        elif r["model"].startswith("claude"):
            cell["ref"] += price
        else:
            cell["real"] += price
    res = proj / "results"
    for f in sorted(res.glob("[0-9][0-9][0-9].json")) if res.is_dir() else []:
        r = json.loads(f.read_text())
        tier = fc_tiers.tier_of(r["model"])
        if tier:
            cell = out[tier]
            cell["real"] += r.get("cost") or 0.0
            if r.get("reference_cost") is not None:
                cell["ref"] += r["reference_cost"]
            elif r["model"].startswith("claude"):
                cell["unpriced"] = True
    return out

def lines(proj, limit=None):
    s = spend(proj)
    if not any(c["real"] or c["ref"] or c["unpriced"] for c in s.values()):
        return []
    out = [f"  {'tier spend':12} {'real $':>9} {'ref $':>9}"]
    for t in fc_tiers.ORDER:
        c = s[t]
        out.append(f"  {t:12} {c['real']:>9.4f} {c['ref']:>9.4f}" + ("+?" if c["unpriced"] else "")
                   + (f"  limit {limit:.2f}" if t == "frontier" and limit is not None else ""))
    return out

def frontier(proj):
    s = spend(proj)
    return s["frontier"]["real"] + s["frontier"]["ref"]
