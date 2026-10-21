"""Ik wil huren (MVGM): the site's map feed /aanbod/feed/projects.json holds ALL objects (NL-wide,
~1000) with lat/lng and the rendered card HTML (address, postcode, city, status, price, m2, bedrooms).
One gzip request (~130 KB) per check, filtered client-side on city -> every ~4 min.
The card price is the bare rent (service costs only on the detail page) -> service = unknown."""
import html as htmlmod, json, re
from .common import request, listing, num

KEY, NAME, PREFIX, EVERY_S = "ikwilhuren", "Ik wil huren (MVGM)", "ikwilhuren:", 300
BASE = "https://ikwilhuren.nu"
CITY = "rotterdam"

def _g(pat, s):
    m = re.search(pat, s, re.S)
    return htmlmod.unescape(re.sub(r"\s+", " ", m.group(1))).strip() if m else None

def fetch():
    raw = request(f"{BASE}/aanbod/feed/projects.json", accept="application/json", extra={"Accept-Encoding": "gzip"})
    d = json.loads(raw)
    if isinstance(d, str): d = json.loads(d)
    items = list(d.values()) if isinstance(d, dict) else d
    if len(items) < 50: raise ValueError(f"feed suspiciously small ({len(items)})")
    out, unparsed = [], 0
    for x in items:
        c = x.get("cardInnerHtml") or ""
        title = _g(r'stretched-link"[^>]*>(.*?)</a>', c); href = _g(r'href="([^"]+)"', c)
        pcc = _g(r'</a>\s*</span>\s*<span>([^<]*)</span>', c) or ""
        m = re.match(r"(\d{4}\s?[A-Z]{2})\s+(.*)", pcc)
        pc, city = (m.group(1), m.group(2)) if m else (None, pcc or None)
        if not title or not href: unparsed += 1; continue
        if (city or "").strip().lower() != CITY: continue
        status = _g(r'status-dot[^"]*"></span>([^<]*)</span>', c)
        price = _g(r'fw-bold">([^<]*)<', c)
        rent = num(re.sub(r"[^\d,]", "", price or "").rstrip(",")) if price else None
        bed = _g(r'<span>(\d+)\s*slaapkamers?</span>', c); m2 = _g(r'<span>(\d+)\s*m<sup>', c)
        out.append(listing(
            slug=PREFIX + (x.get("UUId") or href.strip("/").split("/")[-1]), address=title,
            street=re.sub(r"\s+\d.*$", "", title) or None, postcode=pc, city=city,
            lat=num(x.get("Lat")), lon=num(x.get("Lng")),
            bedrooms=int(bed) if bed else None, m2=int(m2) if m2 else None,
            rent=rent, service=None, status=status,
            status_code="available" if (status or "").lower() == "te huur" else (status or "").lower() or None,
            available=_g(r'fa-calendar[^<]*</i></span>([^<]*)</span>', c), url=BASE + href))
    warn = [f"{unparsed} kaarten niet te parsen"] if unparsed > len(items) * 0.1 else []
    if not out: raise ValueError("0 Rotterdam listings in feed")
    return out, "map_feed_json", False, warn
