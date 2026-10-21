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

def decided_cards(issues, ids):
    """Which of `ids` already head a live line of those issues' Decisions so far (best effort: Linear down means none known)."""
    out = set()
    for issue in dict.fromkeys(issues if fc_config.LINEAR_KEY else []):
        try:
            desc = (fc_linear.linear_gql("query($id: String!) { issue(id: $id) { description } }", {"id": issue})["issue"] or {}).get("description")
        except Exception:  # noqa: BLE001  a Linear outage must not stop an ask
            continue
        lines = fc_change.decision_lines(desc)
        out |= {i for i in ids if any(re.match(rf"[\s*_`(\[]*{re.escape(i)}(?!\w)", l) for l in lines)}
    return out

def ask_gate(proj, who, message):
    """What `report needs-user` sends: the message (a verified link and the text fallback added, repeats marked), or None when it
    must not go out. A card is asked once per reporter: the team lead's forward of the wayfinder's cards is a new ask, its own repeat is not. Exits with the reason when a page link is missing, doubled, or does not answer."""
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
    scope = f"{head[1] or ''}/{head[2]}" if head else "?"
    feature = (json.loads((proj / "linear.json").read_text()) if (proj / "linear.json").exists() else {}).get("feature")
    open_ids = [i for i in ids if i not in decided_cards([x for x in (head[2] if head else None, feature) if x], ids)]
    if not open_ids:
        print(f"not reported: {', '.join(ids)} already in the map's Decisions so far. Build on the decisions; nothing is open.")
        return None
    path = proj / "results" / "asked.json"
    asked = json.loads(path.read_text()) if path.exists() else {}
    key = lambda i: f"{who}/{scope}/{i}"
    old = [i for i in open_ids if key(i) in asked]
    if old and len(old) == len(open_ids):
        first = asked[key(old[0])]
        if not reminder or any(asked[key(i)].get("reminded") for i in old):
            print(f"not reported: {', '.join(old)} already asked at {first['at']} and not answered yet. Wait for the answer; do not ask again."
                  + (" (the one reminder is spent)" if reminder else " If the window closed, one `reminder: ` line may follow."))
            return None
        for i in old:
            asked[key(i)]["reminded"] = True
    for i in open_ids:
        asked.setdefault(key(i), {"at": time.strftime("%Y-%m-%d %H:%M:%S")})
    fc_core.atomic_write(path, json.dumps(asked, indent=1))
    return message
