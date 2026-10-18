"""Shared HTTP helpers for adapters."""
import gzip, json, time, urllib.request

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36",
    "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8", "Cache-Control": "no-cache",
}

def request(url, data=None, accept="text/html,application/xhtml+xml,*/*;q=0.8", attempts=2, timeout=20, extra=None):
    err = None
    h = dict(HEADERS, Accept=accept, **(extra or {}))
    body = None
    if data is not None:
        body = json.dumps(data).encode(); h["Content-Type"] = "application/json"
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, data=body, headers=h, method="POST" if body else "GET")
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding", "").lower() == "gzip": raw = gzip.decompress(raw)
                return raw.decode("utf-8", "replace")
        except Exception as e:  # noqa
            err = e
            if i < attempts - 1: time.sleep(2 * (2 ** i))
    raise RuntimeError(f"fetch failed after {attempts} attempts: {type(err).__name__}: {err}")

def get_json(url, **kw):
    return json.loads(request(url, accept="application/json", **kw))

def post_json(url, data, **kw):
    return json.loads(request(url, data=data, accept="application/json", **kw))

def num(v):
    """'1112,50' / 1112.5 / None -> float|int|None"""
    if v is None or v == "": return None
    if isinstance(v, (int, float)): return v
    s = str(v).strip().replace(".", "").replace(",", ".") if "," in str(v) else str(v).strip()
    try:
        f = float(s); return int(f) if f.is_integer() else f
    except ValueError:
        return None

def listing(**kw):
    """Normalized listing. service=None means 'unknown' (price shown excl. service costs)."""
    base = dict(slug=None, category="rent", address=None, street=None, postcode=None, city=None, lat=None, lon=None,
                type=None, rooms=None, bedrooms=None, m2=None, rent=None, service=None, total=None, status=None,
                status_code=None, published=None, available=None, inquiries=None, energy_label=None, url=None)
    base.update(kw)
    if base["total"] is None and isinstance(base["rent"], (int, float)) and base["service"] is not None:
        base["total"] = base["rent"] + base["service"]
    return base
