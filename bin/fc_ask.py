import json, re, sys, time, urllib.error, urllib.request
import fc_core, fc_config, fc_linear, fc_change


# ---------- one ask per card set: the link must answer, and a card is asked once ----------
SESSION_URL = re.compile(r"https?://[^\s'\"<>()]*?/session/[0-9A-Za-z]+")  # the form `lavish-axi <file>` prints as `url:`
ASK_FALLBACK = "You can also answer the visual cards in text, in this same message."
ASK_HEAD = re.compile(r"^(?:reminder:\s*)?(?:change (C\d+):\s*)?([A-Z][A-Z0-9]*-\d+):")

def url_problem(url):
    """Why a page link does not answer (empty when it does): the check behind "one working link, every time"."""
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(url, timeout=5) as r:  # a proxy never reaches a local page
            return "" if r.status < 400 else f"HTTP {r.status}"
    except urllib.error.HTTPError as e:
        e.close()
        return f"HTTP {e.code}"
    except (OSError, ValueError) as e:
        return str(e)[:100]

def card_ids(message):
    """The card ids a `<n> cards <ids>` line names: `Q1-Q3, W5` is Q1, Q2, Q3, W5. Empty when the line names none."""
    m = re.search(r"\b\d+\s+cards?\s+([^;]+)", message, re.I)
    ids = []
    for tok in re.split(r"[,&\s]+|\band\b", re.sub(r"\s*(?:\.\.|\bto\b|-)\s*", "-", m.group(1))) if m else []:
        r = re.fullmatch(r"([A-Za-z]{0,3})(\d+)-(?:\1)?(\d+)", tok)
        if r and 0 <= int(r[3]) - int(r[2]) < 100:
            ids += [f"{r[1]}{n}" for n in range(int(r[2]), int(r[3]) + 1)]
        elif re.fullmatch(r"[A-Za-z]{0,3}\d+", tok):
            ids.append(tok)
    return list(dict.fromkeys(ids))

def map_bodies(issues):
    """issue -> description, for the issues Linear answers (best effort: no key or Linear down means none known)."""
    out = {}
    for issue in dict.fromkeys(issues if fc_config.LINEAR_KEY else []):
        try:
            out[issue] = (fc_linear.linear_gql("query($id: String!) { issue(id: $id) { description } }", {"id": issue})["issue"] or {}).get("description") or ""
        except Exception:  # noqa: BLE001  a Linear outage must not stop an ask
            continue
    return out

def decided_cards(bodies, ids):
    """Which of `ids` already head a live line of those maps' Decisions so far."""
    out = set()
    for desc in bodies.values():
        lines = fc_change.decision_lines(desc)
        out |= {i for i in ids if any(re.match(rf"[\s*_`(\[]*{re.escape(i)}(?!\w)", l) for l in lines)}
    return out


# ---------- the card format: a question, why it matters, options A-D with what each affects, and a recommendation ----------
CARD_FORMAT = ("`Q1. <question>` / `Why: <why it matters>` / `A. <option> - affects: <what choosing it changes>` (B., C., D. the same, "
               "two options at least) / `Recommendation: <letter> - <why>`")
CARD_HEAD = re.compile(r"^\s*(?:[-*]\s+|\d+[.)]\s+)?[*_`]*([A-Za-z]{0,3}\d+)[*_`]*[.:)][*_`]*\s*(.*)")  # `Q1. question`, `- **Q1**: question`
OPTION = re.compile(r"^\s*(?:[-*]\s+)?[*_`]*([A-D])[*_`]*[.):][*_`]*\s+(.*\S)")
AFFECTS = re.compile(r"\baffects?\b[*_`]*\s*[:\-]?\s*(\S.*)", re.I)
WHY = re.compile(r"^\s*(?:[-*]\s+)?[*_`]*why\b[^:]*:\s*(\S.*)", re.I)
RECOMMENDATION = re.compile(r"^\s*(?:[-*]\s+)?[*_`]*recommend(?:ation|ed)?[*_`]*\s*[:\-]\s*[*_`]*([A-D])\b(.*)", re.I)
SUPERSEDES = re.compile(r"^\s*(?:[-*]\s+)?[*_`]*(?:supersedes|replaces)[*_`]*\s*:\s*(\S.*)", re.I)  # a change-of-course card names the line it questions

def cards_in(section):
    """The cards written in a map's Not yet specified, by id: question, why, options {letter: (text, affects)}, recommendation (letter),
    supersedes (the decision line a change-of-course card questions), and span, the (start, end) of the card's lines in the section.
    A card runs from its `<id>.` line to the next card's."""
    lines = section.splitlines()
    heads = [(i, m) for i, m in ((i, CARD_HEAD.match(l)) for i, l in enumerate(lines)) if m and not OPTION.match(lines[i])]
    cards = {}
    for n, (i, m) in enumerate(heads):
        end = heads[n + 1][0] if n + 1 < len(heads) else len(lines)
        card = {"question": m.group(2).strip(), "why": "", "options": {}, "recommendation": "", "supersedes": "", "span": (i, end)}
        for l in lines[i + 1:end]:
            if o := OPTION.match(l):
                text, aff = o.group(2), AFFECTS.search(o.group(2))
                card["options"][o.group(1)] = (text[:aff.start()].rstrip(" -:;(") if aff else text, aff.group(1).strip(" )") if aff else "")
            elif r := RECOMMENDATION.match(l):
                card["recommendation"] = r.group(1).upper()
            elif w := WHY.match(l):
                card["why"] = w.group(1).strip()
            elif sup := SUPERSEDES.match(l):
                card["supersedes"] = sup.group(1).strip()
        cards.setdefault(m.group(1), card)
    return cards

def card_problems(cid, card):
    """What the card lacks of the format: options A-D in order (two at least), what each affects, and a recommendation among them."""
    letters = "".join(sorted(card["options"]))
    out = []
    if len(letters) < 2 or letters != "ABCD"[:len(letters)]:
        out.append(f"{cid}: options are {', '.join(letters) or 'missing'}; write them as A., B. (C., D.) in order, two at least")
    out += [f"{cid}: option {k} says nothing about what it affects" for k, (_, aff) in sorted(card["options"].items()) if not aff]
    if not card["recommendation"]:
        out.append(f"{cid}: no `Recommendation: <letter>` line")
    elif card["recommendation"] not in card["options"]:
        out.append(f"{cid}: the recommendation names option {card['recommendation']}, which the card has not")
    return out

def format_problems(bodies, ids):
    """Why the asked cards cannot go out as written on the maps: a card missing from every Not yet specified, or short of the format.
    Nothing when no map was read (Linear down): the format is checked where it can be."""
    if not bodies:
        return []
    cards = {}
    for desc in bodies.values():
        for cid, card in cards_in(fc_change.map_section(desc, "Not yet specified")).items():
            cards.setdefault(cid, card)
    out = []
    for i in ids:
        out += card_problems(i, cards[i]) if i in cards else [f"{i} is not written under Not yet specified on {', '.join(bodies)}"]
    return out

class Refused(Exception):
    """A report that must not go out, but is no error of the reporter's command: it is told why, and the attempt is recorded."""

def ask_gate(proj, message, hop=""):
    """What `report needs-user` sends: the message (a verified link and the text fallback added, repeats marked). Exits with the reason
    when a page link is missing, doubled, or does not answer; raises Refused when a card is decided or asked already, or is not on the map in the card format. A card is asked once per `hop`
    (whom the reporter reports to): a teammate's ask to its team lead does not use up the team lead's ask to the engineering manager."""
    urls = list(dict.fromkeys(SESSION_URL.findall(message)))
    if re.search(r"open in Lavish", message, re.I) and not urls:
        sys.exit("not reported: a visual page needs its link in the message. Run `npx -y lavish-axi <file>` and put the `url:` it prints in the line.")
    if len({u.rsplit("/session/", 1)[1] for u in urls}) < len(urls):
        sys.exit(f"not reported: the page is given in {len(urls)} forms ({', '.join(urls)}). Give the one `url:` lavish-axi printed.")
    for u in urls:
        if why := url_problem(u):
            sys.exit(f"not reported: {u} does not answer ({why}). Reopen the page with `npx -y lavish-axi <file>`, use the `url:` it prints, and report again.")
    if urls and ASK_FALLBACK not in message:
        message += f" {ASK_FALLBACK}"
    ids = card_ids(message)
    if not ids:
        return message
    reminder = message.lower().startswith("reminder:")
    head = ASK_HEAD.match(message)
    scope = (f"{hop}@" if hop else "") + (f"{head[1] or ''}/{head[2]}" if head else "?")
    feature = (json.loads((proj / "linear.json").read_text()) if (proj / "linear.json").exists() else {}).get("feature")
    bodies = map_bodies([x for x in (head[2] if head else None, feature) if x])
    open_ids = [i for i in ids if i not in decided_cards(bodies, ids)]
    if not open_ids:
        raise Refused(f"not reported: {', '.join(ids)} already in the map's Decisions so far. Build on the decisions; nothing is open.")
    if problems := format_problems(bodies, open_ids):
        raise Refused(f"not reported: the cards are not in the card format on the map: {'; '.join(problems)}. Write each card under "
                      f"Not yet specified as {CARD_FORMAT}, then report again; the product owner reads them with `compose decisions`.")
    path = proj / "results" / "asked.json"
    asked = json.loads(path.read_text()) if path.exists() else {}
    key = lambda i: f"{scope}/{i}"
    old = [i for i in open_ids if key(i) in asked]
    if old and len(old) == len(open_ids):
        first = asked[key(old[0])]
        if not reminder or any(asked[key(i)].get("reminded") for i in old):
            raise Refused(f"not reported: {', '.join(old)} already asked at {first['at']} and not answered yet. Wait for the answer; do not ask again."
                          + (" (the one reminder is spent)" if reminder else " If the window closed, one `reminder: ` line may follow."))
        for i in old:
            asked[key(i)]["reminded"] = True
    for i in open_ids:
        asked.setdefault(key(i), {"at": time.strftime("%Y-%m-%d %H:%M:%S")})
    fc_core.atomic_write(path, json.dumps(asked, indent=1))
    return message
