#!/usr/bin/env python3
"""Generic rental-listing watcher.

Fetches a server-rendered listing overview, parses the embedded Nuxt payload (sandboxed node `vm`,
fallback: HTML cards), diffs against state/, and POSTs relevant events to a webhook.

Env: MATCH_CONFIG (JSON, required), WEBHOOK_URL, WEBHOOK_KEY (Bearer), SOURCE_URL (optional).
Logs only counts; no listing details or criteria are printed.
"""
import argparse, datetime as dt, html as htmlmod, json, math, os, re, subprocess, sys, time
import urllib.request, urllib.error
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Amsterdam")
URL = os.environ.get("SOURCE_URL") or "https://huuraanbod.hefwonen.nl/huuraanbod"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8", "Cache-Control": "no-cache",
}
RELEVANT = {"NEW", "STATUS_CHANGE", "PRICE_CHANGE", "REAPPEARED"}
REMIND_EVERY = dt.timedelta(minutes=30)
REMIND_WINDOW = (dt.time(7, 0), dt.time(23, 30))
MAX_OUTBOX = 30

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
    return {"match": low(c.get("match_streets", [])), "twijfel": low(c.get("twijfel_streets", [])),
            "pc": tuple(c.get("postcode_prefixes", [])), "radius": c.get("radius_m", 0),
            "refs": [tuple(p) for p in c.get("ref_points", [])], "min_rooms": c.get("min_rooms", 0),
            "max_total": c.get("max_total", 10**9), "city": (c.get("city") or "").lower(),
            "housing_only": c.get("housing_only", True)}

# ---------- fetch / parse ----------
def fetch(url, attempts=3, timeout=20):
    err = None
    for i in range(attempts):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:  # noqa
            err = e
            if i < attempts - 1: time.sleep(2 * (2 ** i))
    raise RuntimeError(f"fetch failed after {attempts} attempts: {type(err).__name__}: {err}")

NODE_JS = r"""
const vm=require('vm');let src='';process.stdin.on('data',d=>src+=d).on('end',()=>{
 const ctx={window:{}};vm.createContext(ctx);
 vm.runInContext(src,ctx,{timeout:2000});
 const s=ctx.window.__NUXT__.state;
 process.stdout.write(JSON.stringify({rent:s.rent||[],bog:s.bog||[],park:s.park||[]}));});
"""

def parse_payload(page):
    i = page.find("window.__NUXT__")
    if i < 0: raise ValueError("Nuxt payload marker missing")
    js = page[i:page.find("</script>", i)]
    p = subprocess.run(["node", "-e", NODE_JS], input=js, capture_output=True, text=True, timeout=15)
    if p.returncode != 0: raise ValueError("node eval failed: " + p.stderr[-300:])
    out = []
    for cat, items in json.loads(p.stdout).items():
        for x in items:
            if not isinstance(x, dict) or not x.get("slug"): continue
            a = x.get("address") or {}; h = x.get("handover") or {}; ch = x.get("characteristic") or {}
            lay = ch.get("layout") or {}; st = x.get("status") or {}
            rent = h.get("price"); svc = h.get("service_costs") or 0
            out.append({"slug": x["slug"], "category": cat, "address": x.get("title"),
                        "street": a.get("street"), "postcode": a.get("postal_code"),
                        "city": (a.get("location") or "").title() or None,
                        "lat": a.get("position_lat"), "lon": a.get("position_long"),
                        "type": ch.get("type"), "rooms": lay.get("number_of_rooms") or None,
                        "m2": ch.get("living_area"), "rent": rent, "service": svc,
                        "total": (rent + svc) if isinstance(rent, (int, float)) else None,
                        "status": st.get("label"), "status_code": st.get("code"),
                        "energy_label": ch.get("energy_label"), "published": x.get("published_at_date"),
                        "available": x.get("available_at_label"),
                        "inquiries": (x.get("statistics") or {}).get("inquiries"),
                        "url": f"{URL}/{x['slug']}"})
    return out, "nuxt_payload"

def _num(s):
    s = re.sub(r"[^\d,]", "", s or "").replace(",", ".")
    try: return float(s) if "." in s else int(s)
    except ValueError: return None

def parse_cards(page):
    out = []
    for card in page.split('class="property"')[1:]:
        m = re.search(r'href="/huuraanbod/([^"]+)"', card)
        if not m: continue
        t = lambda pat: (lambda r: htmlmod.unescape(r.group(1)).strip() if r else None)(re.search(pat, card, re.S))
        title = t(r'property__title[^>]*>([^<]+)<')
        loc = re.search(r'property__location[^>]*><span[^>]*>([^<]*)</span><span[^>]*>([^<]*)<', card)
        pr = {k.strip(): _num(v) for k, v in re.findall(r'<span[^>]*>([^<]+)</span><span class="highlighted[^>]*>([^<]+)<', card)}
        m2 = re.search(r'>(\d+)\s*m²<', card); rooms = re.search(r'details__rooms.*?<span[^>]*>(\d+)', card, re.S)
        rent = pr.get("Huurprijs p.m."); svc = pr.get("Servicekosten p.m.") or 0
        out.append({"slug": m.group(1), "category": "rent?", "address": title,
                    "street": re.sub(r"\s+\d.*$", "", title or "") or None,
                    "postcode": loc.group(1).strip(" ,") if loc else None,
                    "city": loc.group(2).strip().title() if loc else None, "lat": None, "lon": None,
                    "rooms": int(rooms.group(1)) if rooms else None, "m2": int(m2.group(1)) if m2 else None,
                    "rent": rent, "service": svc, "total": rent + svc if rent else None,
                    "status": t(r'property__label"[^>]*>([^<]+)<') or "Beschikbaar?", "status_code": None,
                    "url": f"{URL}/{m.group(1)}"})
    return out, "html_cards_fallback"

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
    reasons = [why]; r, tot = l.get("rooms"), l.get("total")
    if r is None: level = "twijfel"; reasons.append("kamers onbekend")
    elif r < c["min_rooms"]: return "no", reasons + [f"{r} kamers"]
    if tot is None: level = "twijfel"; reasons.append("prijs onbekend")
    elif tot > c["max_total"]: return "no", reasons + [f"totaal €{tot} > €{c['max_total']}"]
    return level, reasons

def available(s):
    return (s or "").lower() in ("available", "beschikbaar")

def ev(kind, l, lvl, reasons, note):
    keys = ("slug", "url", "address", "postcode", "rooms", "m2", "rent", "service", "total", "status",
            "published", "available", "inquiries", "energy_label", "category")
    d = {"type": kind, "match": lvl}; d.update({k: l.get(k) for k in keys})
    d["match_reasons"] = reasons; d["note"] = note
    return d

# ---------- watch (state diff) ----------
def watch(state_path, html_file, cfg):
    t0 = time.time(); ts = now().isoformat()
    st = load_json(state_path, None); first_run = st is None
    st = st or {"listings": {}, "health": {"consecutive_failures": 0}}
    health = st.setdefault("health", {"consecutive_failures": 0})
    events, listings, source, err = [], [], None, None
    try:
        page = open(html_file).read() if html_file else fetch(URL)
        missing = [m for m in ("window.__NUXT__", "property__title", "/huuraanbod/") if m not in page]
        try: listings, source = parse_payload(page)
        except Exception as e:
            listings, source = parse_cards(page); missing.append(f"payload: {e}")
        if not listings: raise ValueError("0 listings parsed")
        if missing: err = "structuur gewijzigd? ontbreekt: " + "; ".join(missing)
    except Exception as e:
        err = str(e)
    prev_fail = health.get("consecutive_failures", 0); fatal = not listings
    if err:
        health["consecutive_failures"] = prev_fail + 1; hstat = "error"
        events.append({"type": "HEALTH", "match": None, "first_failure": prev_fail == 0, "note": err, "fatal": fatal})
        health["last_error"] = err
    else:
        health["consecutive_failures"] = 0; hstat = "ok"
        if prev_fail: events.append({"type": "HEALTH_RECOVERED", "match": None, "note": f"hersteld na {prev_fail} fouten"})
    health.pop("last_check", None); health["last_status"] = hstat
    if listings:
        known = st["listings"]; cur = set()
        for l in listings:
            s = l["slug"]; cur.add(s); lvl, why = match(l, cfg); p = known.get(s)
            if p is None:
                if not first_run:
                    note = "nieuw en beschikbaar" if available(l.get("status_code") or l.get("status")) else "nieuw, al onder optie"
                    events.append(ev("NEW", l, lvl, why, note))
                p = known[s] = {"first_seen": ts}
            else:
                if p.get("removed"):
                    events.append(ev("REAPPEARED", l, lvl, why, "weer op de site")); p.pop("removed", None)
                if p.get("status") != l.get("status"):
                    second = available(l.get("status_code") or l.get("status")) and not available(p.get("status_code") or p.get("status"))
                    events.append(ev("STATUS_CHANGE", l, lvl, why,
                                     f"{p.get('status')} -> {l.get('status')}" + (" (tweede kans!)" if second else "")))
                if p.get("total") is not None and l.get("total") is not None and p.get("total") != l.get("total"):
                    events.append(ev("PRICE_CHANGE", l, lvl, why, f"totaal €{p.get('total')} -> €{l.get('total')}"))
            for k in ("last_seen", "match"): p.pop(k, None)   # volatile / criteria-revealing: not stored
            p.update({k: l.get(k) for k in ("status", "status_code", "rent", "service", "total", "address", "rooms", "published")})
            p["_lvl"] = lvl  # in-memory only, stripped before save
        if source != "html_cards_fallback":
            for s, p in known.items():
                if s not in cur and not p.get("removed"):
                    p["removed"] = ts
                    events.append({"type": "REMOVED", "match": None, "slug": s, "address": p.get("address"), "note": "niet meer op de site"})
        for p in known.values(): p.pop("_lvl", None)
    out = {"ok": not fatal and not err, "checked_at": ts, "source": source, "first_run_seeded": first_run and bool(listings),
           "listing_count": len(listings), "woning_count": sum(1 for l in listings if l.get("category") in ("rent", "rent?")),
           "events": events, "health": {"status": "recovered" if (not err and prev_fail) else hstat,
                                        "consecutive_failures": health["consecutive_failures"], "message": err or "ok"},
           "elapsed_s": round(time.time() - t0, 2)}
    return st, out

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

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state-dir", default="state"); ap.add_argument("--html")
    ap.add_argument("--now"); ap.add_argument("--no-post", action="store_true")
    a = ap.parse_args()
    sp = lambda n: os.path.join(a.state_dir, n)
    url = (os.environ.get("WEBHOOK_URL") or "").strip(); key = (os.environ.get("WEBHOOK_KEY") or "").strip()
    if key.lower().startswith("bearer "): key = key[7:].strip()
    t = dt.datetime.fromisoformat(a.now).astimezone(TZ) if a.now else now()
    ds = load_json(sp("dispatch_state.json"), {}); outbox = ds.get("outbox", [])
    events = []
    try:
        cfg = load_config()
        st, out = watch(sp("hef_state.json"), a.html, cfg)
        save_json(sp("hef_state.json"), st)
        if ds.pop("crashing", False):
            events.append({"type": "HEALTH_RECOVERED", "match": None, "note": "watcher draait weer"})
    except Exception as e:
        out = {"ok": False, "events": [], "health": {"status": "error", "message": type(e).__name__}}
        if not ds.get("crashing"):
            events.append({"type": "HEALTH", "match": None, "first_failure": True, "fatal": True,
                           "note": f"watcher crashte: {type(e).__name__}"})
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
    in_window = REMIND_WINDOW[0] <= t.time() < REMIND_WINDOW[1]
    last = ds.get("last_reminder")
    due = not last or t - dt.datetime.fromisoformat(last) >= REMIND_EVERY
    if pend and in_window and (due or reasons):
        events.append({"type": "REMINDER", "match": "match", "items": pend,
                       "note": f"{len(pend)} passende woning(en) wachten nog op reactie"})
        reasons.append("REMINDER"); ds["last_reminder"] = t.isoformat()
    if reasons:
        outbox.append({"reason": "+".join(reasons), "test": False, "sent_at": t.isoformat(), "ok": out.get("ok"),
                       "checked_at": out.get("checked_at"), "source": out.get("source"),
                       "listing_count": out.get("listing_count"), "woning_count": out.get("woning_count"),
                       "health": out.get("health"), "pending_count": len(pend), "events": events})
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
    print(json.dumps({"ok": out.get("ok"), "listing_count": out.get("listing_count"), "source": out.get("source"),
                      "raw_event_types": types, "sent_reasons": reasons, "post_results": results,
                      "outbox_left": len(outbox), "health": (out.get("health") or {}).get("status"),
                      "elapsed_s": out.get("elapsed_s")}))
    if a.no_post and reasons and os.environ.get("PRINT_PAYLOAD"):
        print(json.dumps(outbox[-1], ensure_ascii=False))
    return 0

if __name__ == "__main__":
    sys.exit(main())
