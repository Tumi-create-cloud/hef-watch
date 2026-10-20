#!/usr/bin/env python3
"""Generic rental-listing watcher over several platform adapters (see adapters/).

Each check: fetch due platforms in parallel, diff against state/, POST relevant events to a webhook.
Env: MATCH_CONFIG (JSON, required), WEBHOOK_URL, WEBHOOK_KEY (Bearer).
Logs only counts; no listing details or criteria are printed.
"""
import argparse, datetime as dt, json, math, os, sys, time
import urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor
from zoneinfo import ZoneInfo
from adapters import ADAPTERS

TZ = ZoneInfo("Europe/Amsterdam")
HEALTH_ALERT_AFTER_S = 15 * 60   # only alert when a platform has been failing continuously this long
RELEVANT = {"NEW", "STATUS_CHANGE", "PRICE_CHANGE", "REAPPEARED"}
REMIND_EVERY = dt.timedelta(minutes=30)
REMIND_WINDOW = (dt.time(7, 0), dt.time(23, 30))
MAX_OUTBOX = 30
STORED = ("status", "status_code", "rent", "service", "total", "address", "rooms", "bedrooms", "published")

def now():
    return dt.datetime.now(TZ).replace(microsecond=0)

def load_json(p, default):
    try:
        with open(p) as f: return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default

def save_json(p, obj):
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w") as f: json.dump(obj, f, ensure_ascii=False, indent=1, sort_keys=True); f.write("\n")
    os.replace(tmp, p)

def load_config():
    c = json.loads(os.environ["MATCH_CONFIG"])
    low = lambda xs: {s.strip().lower() for s in xs}
    mx = c.get("max_total", 10**9)
    return {"match": low(c.get("match_streets", [])), "twijfel": low(c.get("twijfel_streets", [])),
            "pc": tuple(c.get("postcode_prefixes", [])), "radius": c.get("radius_m", 0),
            "refs": [tuple(p) for p in c.get("ref_points", [])], "min_rooms": c.get("min_rooms", 0),
            "max_total": mx, "excl_twijfel": c.get("twijfel_rent_excl_above", mx - 100),
            "city": (c.get("city") or "").lower(), "housing_only": c.get("housing_only", True)}

# ---------- matching ----------
def dist_m(a, b):
    dy = (a[0] - b[0]) * 111320; dx = (a[1] - b[1]) * 111320 * math.cos(math.radians(a[0]))
    return (dx * dx + dy * dy) ** 0.5

def match(l, c):
    if c["housing_only"] and l.get("category") in ("bog", "park"): return "no", ["geen woning"]
    street = (l.get("street") or "").strip().lower(); pc = (l.get("postcode") or "").replace(" ", "")
    city_ok = not c["city"] or (l.get("city") or c["city"]).lower() == c["city"]
    near = None
    if l.get("lat") and l.get("lon") and c["refs"]:
        near = min(dist_m((l["lat"], l["lon"]), p) for p in c["refs"])
    if street in c["match"] and city_ok:
        why = f"straat {l.get('street')}"; level = "match"
    elif (street in c["twijfel"] and city_ok) or (c["pc"] and pc.startswith(c["pc"])) or \
         (near is not None and near < c["radius"]):
        level = "twijfel"
        why = f"locatie twijfel ({l.get('street')}, {l.get('postcode')}" + (f", {int(near)} m)" if near else ")")
    else:
        return "no", ["buiten zoekgebied"]
    reasons = [why]
    r, b = l.get("rooms"), l.get("bedrooms")
    if b is not None and b >= 2: r = max(r or 0, 3)          # >=2 bedrooms counts as >=3 rooms
    elif r is None and b == 1: r = 2
    if r is None: level = "twijfel"; reasons.append("kamers onbekend")
    elif r < c["min_rooms"]: return "no", reasons + [f"{r} kamers"]
    rent, tot = l.get("rent"), l.get("total")
    if l.get("service") is None and rent is not None:          # price excl. unknown service costs
        if rent > c["max_total"]: return "no", reasons + [f"kale huur €{rent} > €{c['max_total']}"]
        reasons.append("servicekosten onbekend")
        if rent > c["excl_twijfel"]: level = "twijfel"
    elif tot is None: level = "twijfel"; reasons.append("prijs onbekend")
    elif tot > c["max_total"]: return "no", reasons + [f"totaal €{tot} > €{c['max_total']}"]
    return level, reasons

def available(s):
    return (s or "").lower() in ("available", "beschikbaar")

def ev(kind, l, lvl, reasons, note, platform):
    keys = ("slug", "url", "address", "postcode", "city", "rooms", "bedrooms", "m2", "rent", "service", "total",
            "status", "published", "available", "inquiries", "energy_label", "category")
    d = {"type": kind, "platform": platform, "match": lvl}; d.update({k: l.get(k) for k in keys})
    d["match_reasons"] = reasons; d["note"] = note
    return d

# ---------- state ----------
def migrate(st):
    st.setdefault("listings", {})
    ph = st.setdefault("platform_health", {})
    if "health" in st: ph["hef"] = st.pop("health")
    seeded = st.setdefault("seeded", [])
    if "hef" not in seeded and st["listings"]: seeded.append("hef")
    for p in st["listings"].values(): p.setdefault("p", "hef")
    return st

def run_platform(ad):
    t0 = time.time()
    try:
        listings, source, partial, warn = ad.fetch()
        if not listings: raise ValueError("0 listings parsed")
        return ad, listings, source, partial, ("structuur gewijzigd? " + "; ".join(warn)) if warn else None, round(time.time() - t0, 2)
    except Exception as e:
        return ad, [], None, False, str(e)[:300], round(time.time() - t0, 2)

def watch(state_path, runtime_path, cfg, only=None, force=False):
    ts = now().isoformat()
    st = load_json(state_path, None)
    st = migrate(st or {"listings": {}})
    rt = load_json(runtime_path, {})          # not committed: last fetch per platform (this runner only)
    t = time.time()
    due = [a for a in ADAPTERS if (not only or a.KEY in only) and
           (force or t - rt.get(a.KEY, 0) >= a.EVERY_S - 20)]
    with ThreadPoolExecutor(max_workers=len(due) or 1) as ex:
        results = list(ex.map(run_platform, due))
    events, summary = [], {}
    for ad, listings, source, partial, err, secs in results:
        rt[ad.KEY] = t
        h = st["platform_health"].setdefault(ad.KEY, {"consecutive_failures": 0})
        prev = h.get("consecutive_failures", 0)
        if prev and not h.get("failing_since"):   # outage from before time-based alerting: HEALTH was already sent
            h["failing_since"] = ts; h["alerted"] = True
        if err:
            if not prev: h["failing_since"] = ts; h["alerted"] = False
            h["consecutive_failures"] = prev + 1; h["last_status"] = "error"; h["last_error"] = err
            down_s = (dt.datetime.fromisoformat(ts) - dt.datetime.fromisoformat(h["failing_since"])).total_seconds()
            alert = not h.get("alerted") and down_s >= HEALTH_ALERT_AFTER_S
            if alert: h["alerted"] = True
            events.append({"type": "HEALTH", "platform": ad.NAME, "match": None, "first_failure": alert,
                           "down_min": round(down_s / 60), "since": h["failing_since"],
                           "note": f"{ad.NAME}: {err} (al {round(down_s / 60)} min onbereikbaar)", "fatal": not listings})
        else:
            alerted = h.get("alerted"); since = h.get("failing_since")
            h["consecutive_failures"] = 0; h["last_status"] = "ok"
            for k in ("failing_since", "alerted"): h.pop(k, None)
            if prev and alerted:
                events.append({"type": "HEALTH_RECOVERED", "platform": ad.NAME, "match": None,
                               "note": f"{ad.NAME}: hersteld na {prev} fouten" + (f" (storing sinds {since[11:16]})" if since else "")})
            elif prev:
                events.append({"type": "HEALTH_BLIP", "platform": ad.NAME, "match": None,
                               "note": f"{ad.NAME}: korte storing ({prev} fouten), stil hersteld"})
        summary[ad.KEY] = {"n": len(listings), "src": source, "ok": not err, "s": secs}
        if not listings: continue
        first = ad.KEY not in st["seeded"]
        known = st["listings"]; cur = set()
        for l in listings:
            s = l["slug"]; cur.add(s); lvl, why = match(l, cfg); p = known.get(s)
            if p is None:
                if not first:
                    note = "nieuw en beschikbaar" if available(l.get("status_code") or l.get("status")) else "nieuw, niet beschikbaar"
                    events.append(ev("NEW", l, lvl, why, note, ad.NAME))
                p = known[s] = {"first_seen": ts, "p": ad.KEY}
            else:
                if p.get("removed"):
                    events.append(ev("REAPPEARED", l, lvl, why, "weer op de site", ad.NAME)); p.pop("removed", None)
                if p.get("status") != l.get("status"):
                    second = available(l.get("status_code") or l.get("status")) and not available(p.get("status_code") or p.get("status"))
                    events.append(ev("STATUS_CHANGE", l, lvl, why,
                                     f"{p.get('status')} -> {l.get('status')}" + (" (tweede kans!)" if second else ""), ad.NAME))
                if p.get("total") is not None and l.get("total") is not None and p.get("total") != l.get("total"):
                    events.append(ev("PRICE_CHANGE", l, lvl, why, f"totaal €{p.get('total')} -> €{l.get('total')}", ad.NAME))
                elif p.get("service") is None and l.get("service") is None and p.get("rent") is not None \
                        and l.get("rent") is not None and p.get("rent") != l.get("rent"):
                    events.append(ev("PRICE_CHANGE", l, lvl, why, f"huur €{p.get('rent')} -> €{l.get('rent')}", ad.NAME))
            for k in ("last_seen", "match"): p.pop(k, None)
            for k in STORED:
                if l.get(k) is not None or k in p: p[k] = l.get(k)
        if first: st["seeded"].append(ad.KEY); summary[ad.KEY]["seeded"] = True
        if not partial:
            for s, p in known.items():
                if p.get("p") == ad.KEY and s not in cur and not p.get("removed"):
                    p["removed"] = ts
                    events.append({"type": "REMOVED", "platform": ad.NAME, "match": None, "slug": s,
                                   "address": p.get("address"), "note": "niet meer op de site"})
    st["seeded"].sort()
    ok = all(v["ok"] for v in summary.values())
    hef = summary.get("hef", {})
    out = {"ok": ok, "checked_at": ts, "platforms": summary, "events": events,
           "listing_count": sum(v["n"] for v in summary.values()),
           "health": {"status": "ok" if ok else "error",
                      "failing": [k for k, v in st["platform_health"].items() if v.get("consecutive_failures")]},
           "source": hef.get("src"), "woning_count": hef.get("n")}
    return st, rt, out

# ---------- dispatch ----------
def post(url, key, payload):
    req = urllib.request.Request(url, data=json.dumps(payload, ensure_ascii=False).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r: return 200 <= r.status < 300, r.status
    except urllib.error.HTTPError as e: return False, e.code
    except Exception as e: return False, type(e).__name__

def pending_items(p):
    raw = load_json(p, None)
    if raw is None: save_json(p, []); return []
    if isinstance(raw, dict): raw = raw.get("items", raw.get("pending", list(raw.values())))
    return [x for x in raw if x] if isinstance(raw, list) else []

def report(state_dir, cfg):
    """Local use only: print current match/twijfel listings of all platforms (fetches everything)."""
    rows = []
    for ad, listings, source, partial, err, secs in map(run_platform, ADAPTERS):
        print(f"# {ad.NAME}: {len(listings)} listings, src={source}, err={err}", file=sys.stderr)
        for l in listings:
            lvl, why = match(l, cfg)
            if lvl != "no": rows.append({"platform": ad.NAME, "match": lvl, "why": why, **{k: l.get(k) for k in
                                         ("address", "city", "rooms", "bedrooms", "m2", "rent", "service", "total", "status", "url")}})
    print(json.dumps(rows, ensure_ascii=False, indent=1))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state-dir", default="state"); ap.add_argument("--only", help="comma list of platform keys")
    ap.add_argument("--force", action="store_true", help="fetch all platforms regardless of interval")
    ap.add_argument("--now"); ap.add_argument("--no-post", action="store_true")
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args()
    sp = lambda n: os.path.join(a.state_dir, n)
    if a.report: report(a.state_dir, load_config()); return 0
    url = (os.environ.get("WEBHOOK_URL") or "").strip(); key = (os.environ.get("WEBHOOK_KEY") or "").strip()
    if key.lower().startswith("bearer "): key = key[7:].strip()
    t = dt.datetime.fromisoformat(a.now).astimezone(TZ) if a.now else now()
    ds = load_json(sp("dispatch_state.json"), {}); outbox = ds.get("outbox", [])
    events, out = [], {}
    try:
        cfg = load_config()
        st, rt, out = watch(sp("hef_state.json"), sp(".runtime.json"), cfg,
                            only=set(a.only.split(",")) if a.only else None, force=a.force)
        save_json(sp("hef_state.json"), st); save_json(sp(".runtime.json"), rt)
        if ds.pop("crashing", False):
            events.append({"type": "HEALTH_RECOVERED", "platform": "watcher", "match": None, "note": "watcher draait weer"})
    except Exception as e:
        out = {"ok": False, "events": [], "health": {"status": "error", "message": type(e).__name__}}
        if not ds.get("crashing"):
            events.append({"type": "HEALTH", "platform": "watcher", "match": None, "first_failure": True, "fatal": True,
                           "note": f"watcher crashte: {type(e).__name__}: {str(e)[:200]}"})
        ds["crashing"] = True
    for e in out.get("events", []):
        k = e.get("type")
        if (k in RELEVANT and e.get("match") in ("match", "twijfel")) or \
           (k == "HEALTH" and e.get("first_failure") is True) or k == "HEALTH_RECOVERED":
            events.append(e)
    reasons = []
    if any(e["type"] in RELEVANT for e in events): reasons.append("ALERT")
    if any(e["type"] == "HEALTH" for e in events): reasons.append("HEALTH")
    if any(e["type"] == "HEALTH_RECOVERED" for e in events): reasons.append("RECOVERED")
    pend = pending_items(sp("hef_pending.json"))
    if "ALERT" in reasons:  # verse melding: herinneringsklok start nu, eerste reminder pas na 30 min
        ds["last_reminder"] = t.isoformat()
    in_window = REMIND_WINDOW[0] <= t.time() < REMIND_WINDOW[1]
    last = ds.get("last_reminder")
    due = not last or t - dt.datetime.fromisoformat(last) >= REMIND_EVERY
    if pend and in_window and (due or (reasons and "ALERT" not in reasons)):
        events.append({"type": "REMINDER", "match": "match", "items": pend,
                       "note": f"{len(pend)} passende woning(en) wachten nog op reactie"})
        reasons.append("REMINDER"); ds["last_reminder"] = t.isoformat()
    if reasons:
        outbox.append({"reason": "+".join(reasons), "test": False, "sent_at": t.isoformat(), "ok": out.get("ok"),
                       "checked_at": out.get("checked_at"), "platforms": out.get("platforms"),
                       "listing_count": out.get("listing_count"), "health": out.get("health"),
                       "pending_count": len(pend), "events": events})
    outbox = outbox[-MAX_OUTBOX:]
    results = []
    if a.no_post:
        results.append("no-post")
    else:
        while outbox:
            if not url or not key: results.append("no_secrets"); break
            ok, code = post(url, key, outbox[0]); results.append(code)
            if not ok: break
            outbox.pop(0)
    if outbox: ds["outbox"] = outbox
    else: ds.pop("outbox", None)
    save_json(sp("dispatch_state.json"), ds)
    types = {}
    for e in out.get("events", []): types[e["type"]] = types.get(e["type"], 0) + 1
    print(json.dumps({"ok": out.get("ok"), "platforms": out.get("platforms"), "raw_event_types": types,
                      "sent_reasons": reasons, "post_results": results, "outbox_left": len(outbox)}))
    if a.no_post and reasons and os.environ.get("PRINT_PAYLOAD"):
        print(json.dumps(outbox[-1], ensure_ascii=False))
    return 0

if __name__ == "__main__":
    sys.exit(main())
