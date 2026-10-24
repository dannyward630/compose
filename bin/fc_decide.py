"""The project's pending decisions, on one page (`compose decisions`), and the one way a decision is recorded (`compose decide`):
with the product owner's words attached, or as an unconfirmed recommendation while away or yolo is on."""
import json, re, sys, time
import fc_core, fc_tasks, fc_linear, fc_linear_cmd, fc_plan, fc_herdr, fc_change, fc_ask


# ---------- the map's two decision sections ----------
OPEN, DECIDED = "Not yet specified", "Decisions so far"
UNCONFIRMED = "({mode} recommendation, unconfirmed, {date})"  # the tag on a line the engineering manager decided for the product owner
CONFIRMED = '(product owner, {date}; said: "{quote}")'       # the tag on a line the product owner decided, their words attached
ANSWER = re.compile(rf"^\s*({fc_ask.CARD_ID})\s*[:=.]\s*(.+?)\s*$")  # `Q1: A`, `Q2: B, but keep the old route`
KEEP = re.compile(r"^keep\b", re.I)  # a change-of-course option that leaves the superseded line standing

def map_issue(proj, a):
    """The map whose cards are in question: --issue, else the project's feature."""
    if getattr(a, "issue", None):
        return a.issue
    meta = json.loads((proj / "linear.json").read_text()) if (proj / "linear.json").exists() else {}
    if not meta.get("feature"):
        sys.exit(f"{proj.name} has no feature issue in linear.json; pass --issue <id>")
    return meta["feature"]

def read_map(issue):
    """(Linear id, identifier, description) of the map."""
    got = fc_linear.linear_gql("query($id: String!) { issue(id: $id) { id identifier description } }", {"id": issue})["issue"]
    if not got:
        sys.exit(f"no issue {issue} on Linear")
    return got["id"], got["identifier"], got.get("description") or ""

def heading_line(body, name):
    """The map's heading line for the section, as written (`## Not yet specified`), or the plain `## <name>` when the map has none yet."""
    m = re.search(rf"^(#+[ \t]*{re.escape(name)}[^\n]*)$", body, re.M)
    return m.group(1) if m else f"## {name}"

def asked_at(proj):
    """card id -> when it was first asked, from results/asked.json, whatever the hop and issue."""
    path = proj / "results" / "asked.json"
    asked = json.loads(path.read_text()) if path.exists() else {}
    out = {}
    for key, rec in asked.items():
        out.setdefault(key.rsplit("/", 1)[-1], rec["at"])
    return out

def decided_line(body, cid):
    """The live Decisions so far line the card heads, or None."""
    return next((l for l in fc_change.decision_lines(body) if re.match(rf"[\s*_`(\[]*{re.escape(cid)}(?!\w)", l)), None)


# ---------- `compose decisions`: the page the product owner opens, instead of cards pasted into chat ----------
def card_text(cid, card, asked):
    """One card as the page shows it: id, question, why, options with what each affects, the recommendation, and when it was asked."""
    out = [f"{cid}. {card['question']}" + (f"  (asked {asked[cid]})" if cid in asked else "  (not asked yet)")]
    if card["why"]:
        out.append(f"   Why: {card['why']}")
    for k, (text, aff) in sorted(card["options"].items()):
        out.append(f"   {k}. {text}" + (f" - affects: {aff}" if aff else ""))
    out.append(f"   Recommendation: {card['recommendation'] or '(none)'}")
    out += [f"   format: {p}" for p in fc_ask.card_problems(cid, card)]
    return "\n".join(out)

def decisions_page(proj, ident, body, asked):
    """The project's pending decisions: every open card in full, then the decisions already recorded, newest last."""
    cards = fc_ask.cards_in(fc_change.map_section(body, OPEN))
    decided = fc_change.decision_lines(body)
    unconfirmed = [l for l in decided if "unconfirmed" in l]
    out = [f"{proj.name}: {len(cards)} open card(s) on {ident}" + (f", {len(unconfirmed)} decision(s) to confirm" if unconfirmed else "")]
    for cid, card in cards.items():
        out += ["", card_text(cid, card, asked)]
    if not cards:
        out += ["", "nothing open: Not yet specified is empty"]
    out += ["", f"Decisions so far ({len(decided)}):"] + [f"- {l}" for l in decided] or []
    accept = ", ".join(f"{cid}: {card['recommendation']}" for cid, card in cards.items() if card["recommendation"])
    if cards:
        out += ["", f"answer with `compose decide --project {proj.name} --quote \"<your words>\" \"{accept or 'Q1: A'}\"`, "
                    f"or `--accept-all` for every recommendation"]
    return "\n".join(out)

def cmd_decisions(a):
    """Print the project's pending-decisions page: open cards in full, with what was asked when, and the decisions recorded so far."""
    proj = fc_core.project_dir(a)
    issue = map_issue(proj, a)
    _, ident, body = read_map(issue)
    print(decisions_page(proj, ident, body, asked_at(proj)))


# ---------- `compose decide`: a decision lands on the map only with the product owner's words, or tagged unconfirmed under away/yolo ----------
def parse_answers(words):
    """`Q1: A` pairs -> [(card id, answer)]; a word that is not one is refused."""
    out = []
    for w in words:
        m = ANSWER.match(w)
        if not m:
            sys.exit(f'not recorded: {w!r} is not an answer; write each as "<card id>: <letter or answer>", e.g. "Q1: A"')
        out.append((m.group(1), m.group(2)))
    return out

def answer_text(cid, card, answer):
    """The decision's text: a letter becomes `A. <option>` (plus anything after it); other words stay as given."""
    m = re.match(r"^([A-Da-d])\b[.)]?\s*(.*)$", answer)
    if m and m.group(1).upper() in card["options"]:
        letter = m.group(1).upper()
        rider = m.group(2).strip(" ,;:-")
        return f"{letter}. {card['options'][letter][0]}" + (f" ({rider})" if rider else "")
    if m and not m.group(2).strip():
        sys.exit(f"not recorded: {cid} has no option {m.group(1).upper()}; it has {', '.join(sorted(card['options']))}")
    return answer

def superseded(live, card, change):
    """The live Decisions so far line a change-of-course card's `Supersedes:` names, when the map still has it."""
    want = " ".join(card["supersedes"].split()).strip("~ ")
    return next((l for l in live if want and (want in l or " ".join(l.split()).startswith(want))), None) if change else None

def record(body, answers, tag, change=None):
    """The map with each card moved from Not yet specified to a Decisions so far line, `<id>: <text> <tag>`; an unconfirmed line the
    card already has is replaced, a confirmed one refuses (a change goes through `compose change`). Under a change of course the
    card's `Supersedes:` line is struck through, `~~<old>~~ (<change>)`, unless the answer keeps it. Lines struck earlier stay as they are."""
    section = fc_change.map_section(body, OPEN)
    cards = fc_ask.cards_in(section)
    lines = section.splitlines()
    drop = set()
    dec = fc_change.map_section(body, DECIDED).splitlines()  # every line of the section, struck ones included
    live = lambda: {m.group(1): i for i, m in enumerate(map(fc_change.LIST_ITEM.match, dec)) if m and "~~" not in m.group(1)}
    out = []
    for cid, answer in answers:
        if cid not in cards:
            sys.exit(f"not recorded: no card {cid} under Not yet specified; the open cards are {', '.join(cards) or 'none'}")
        text = answer_text(cid, cards[cid], answer)
        line = f"{cid}: {text} {tag}"
        old = decided_line(body, cid)
        if old and "unconfirmed" not in old:
            sys.exit(f"not recorded: {cid} is already decided ({old}); a change of a decision goes through `compose change start`")
        if old:
            dec[live()[old]] = f"- {line}"
        else:
            dec.append(f"- {line}")
        if (gone := superseded(live(), cards[cid], change)) and not KEEP.match(text.split(". ", 1)[-1]):
            dec[live()[gone]] = f"- ~~{gone}~~ ({change})"
        drop |= set(range(*cards[cid]["span"]))
        out.append(line)
    kept = "\n".join(l for i, l in enumerate(lines) if i not in drop).strip()
    body = fc_plan.replace_section(body, heading_line(body, OPEN), kept or heading_line(body, OPEN))  # an emptied section keeps its heading
    body = fc_plan.replace_section(body, heading_line(body, DECIDED), "\n".join(dec))
    return body, out

def cmd_decide(a):
    """Record the product owner's answers on the map, their words attached (`--quote`), and tell the team lead. Without --quote it
    refuses, unless away or yolo is on: then the recommendation lands tagged unconfirmed and is logged for the digest. With
    --change <id>, the line carries the change's id and the decision line the card supersedes is struck through."""
    proj = fc_core.project_dir(a)
    quote = " ".join((a.quote or "").split())
    posture = fc_tasks.yolo_state(proj)
    if not quote and not posture:
        sys.exit('not recorded: a decision is recorded only with the product owner\'s words: add --quote "<their message, verbatim>". '
                 "While away or yolo is on, `compose decide` without --quote records the recommendation as unconfirmed.")
    if not a.answers and not a.accept_all:
        sys.exit('decide needs answers ("Q1: A" ...) or --accept-all')
    issue = map_issue(proj, a)
    lid, ident, body = read_map(issue)
    cards = fc_ask.cards_in(fc_change.map_section(body, OPEN))
    answers = parse_answers(a.answers or [])
    if a.accept_all:
        given = {cid for cid, _ in answers}
        missing = [cid for cid, c in cards.items() if cid not in given and not c["recommendation"]]
        if missing:
            sys.exit(f"not recorded: --accept-all needs a recommendation on every open card; {', '.join(missing)} carry none")
        answers += [(cid, c["recommendation"]) for cid, c in cards.items() if cid not in given]
    if not answers:
        sys.exit(f"nothing to record: Not yet specified on {ident} is empty")
    date = time.strftime("%Y-%m-%d")
    tag = CONFIRMED.format(date=date, quote=quote.replace('"', "'")) if quote else UNCONFIRMED.format(mode=posture["mode"], date=date)
    change = getattr(a, "change", None)
    if change:
        tag = f"({change}; " + tag[1:]
    new_body, lines = record(body, answers, tag, change)
    fc_linear.linear_gql("mutation($id: String!, $in: IssueUpdateInput!) { issueUpdate(id: $id, input: $in) { success } }", {"id": lid, "in": {"description": new_body}})
    fc_linear_cmd.await_write(lambda: fc_linear.linear_gql("query($id: String!) { issue(id: $id) { description } }", {"id": lid})["issue"]["description"], body, new_body)
    if posture and not quote:
        posture["decisions"] += [{"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "text": l} for l in lines]
        fc_core.atomic_write(proj / "results" / "yolo.json", json.dumps(posture, indent=2))
    for l in lines:
        print(f"recorded on {ident}: {l}")
    left = len(cards) - len(answers)
    print(f"{left} card(s) still open on {ident}" if left else f"Not yet specified on {ident} is empty")
    lead = fc_herdr.agent_name(proj.name, "orchestrator")
    note = f"decided on {ident}: {', '.join(cid for cid, _ in answers)}; read the map's Decisions so far and continue (tell the architect, if one is live)"
    if fc_herdr.herdr_env() and fc_herdr.herdr("agent", "prompt", lead, note) is not None:
        print(f"told {lead}")
    else:
        print(f"tell the team lead: herdr agent prompt {lead} \"{note}\"")
