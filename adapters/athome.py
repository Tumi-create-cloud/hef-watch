"""At Home Vastgoed: JSON endpoint behind the infinite-scroll listing (/api/search-properties).
12 per page (~145 KB), currently 2 pages, so every ~4 min. Bedrooms only; price often excl. service costs."""
from .common import get_json, listing, num

KEY, NAME, PREFIX, EVERY_S = "athome", "At Home Vastgoed", "athome:", 300
BASE = "https://athomevastgoed.nl"
AVAILABLE = {"new", "active", "available"}

def fetch():
    out, page, last = [], 1, 1
    while page <= last and page <= 6:
        d = get_json(f"{BASE}/api/search-properties?list=1&page={page}", extra={"X-Requested-With": "XMLHttpRequest"})
        if "data" not in d: raise ValueError("response without 'data'")
        last = d.get("last_page") or 1
        for x in d["data"]:
            st = x.get("status") or {}; slug = (st.get("attribute") or {}).get("slug")
            incl = (x.get("ah_price_includes_short") or "").lower().startswith("incl")
            out.append(listing(
                slug=f"{PREFIX}{x['id']}", address=x.get("listingAddressIn") or x.get("street"),
                street=x.get("street"), postcode=x.get("postcode"), city=(x.get("location") or {}).get("name"),
                type=((x.get("type") or {}).get("attribute") or {}).get("slug"),
                bedrooms=x.get("no_bedrooms"), m2=x.get("area"),
                rent=num(x.get("ah_price")) if str(x.get("show_price")) == "1" else None,
                service=0 if incl else None, status=st.get("value"),
                status_code="available" if slug in AVAILABLE else slug,
                available=x.get("available_on"), url=x.get("url")))
        page += 1
    return out, "json_api", False, []
