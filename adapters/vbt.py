"""VBT Verhuurmakelaars: public JSON API used by the site's search (POST /api/properties/search),
server-side filtered on city. One light request per check."""
import re
from .common import post_json, listing

KEY, NAME, PREFIX, EVERY_S = "vbt", "VBT Verhuurmakelaars", "vbt:", 300
BASE = "https://vbtverhuurmakelaars.nl"
CITY = "Rotterdam"
STATUS = {"available": "Beschikbaar", "option": "Onder optie", "rentreserved": "Verhuurd onder voorbehoud",
          "rentinuse": "Verhuurd", "underbid": "Onder bod", "inprogress": "In uitvoering"}

def fetch():
    out, page, pages = [], 1, 1
    while page <= pages and page <= 5:
        d = post_json(f"{BASE}/api/properties/search", {"limit": 200, "page": page, "filter": {"city": CITY}}, timeout=30)
        if "houses" not in d: raise ValueError("response without 'houses'")
        pages = d.get("pageCount") or 1
        for x in d["houses"]:
            a = x.get("address") or {}; r = ((x.get("prices") or {}).get("rental")) or {}
            st = (x.get("status") or {}).get("name")
            house = a.get("house") or ""; coord = x.get("coordinate") or [None, None]
            path = x.get("url") or ""
            out.append(listing(
                slug=PREFIX + (path.rstrip("/").split("/")[-1] or x.get("id")), address=house,
                street=re.sub(r"\s+\d.*$", "", house) or None, city=a.get("city"),
                lat=coord[1] if len(coord) > 1 else None, lon=coord[0] if coord else None,
                type=((x.get("attributes") or {}).get("type") or {}).get("category"),
                rooms=x.get("rooms") or None, m2=x.get("plot") or None,
                rent=r.get("price") or None, service=r.get("serviceCharges"),
                status=STATUS.get(st, st), status_code=st, available=(x.get("acceptance") or "")[:10] or None,
                inquiries=x.get("interestedParties"), url=BASE + path))
        page += 1
    return out, "json_api", False, []
