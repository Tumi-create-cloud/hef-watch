"""Vesteda: JSON endpoint behind the public search on vesteda.com (POST /api/units/search/facet,
the same call the Vue search app makes; hurenbij.vesteda.com itself is the login portal).
One request around Rotterdam centre (radius 15 km, ~150 KB), filtered on city -> every ~4 min.
'objects' are the individual units (all statuses); 'complexes' are project pages without unit data and are skipped.
The price is the bare rent (service costs only on the detail page) -> service = unknown."""
from .common import post_json, listing, num

KEY, NAME, PREFIX, EVERY_S = "vesteda", "Vesteda", "vesteda:", 240
BASE = "https://www.vesteda.com"
CITY = "rotterdam"
QUERY = {"filters": [], "latitude": 51.922896, "longitude": 4.463173, "place": "Rotterdam", "placeType": 1,
         "radius": 15, "sorting": 0, "priceFrom": 0, "priceTo": 9999, "language": "nl"}
STATUS = {1: ("Te huur", "available"), 5: ("Nieuw", "available"), 2: ("Verhuurd", "rented"),
          3: ("Verhuurd onder voorbehoud", "rented_reserved"), 4: ("Gereserveerd", "reserved")}

def fetch():
    d = post_json(f"{BASE}/api/units/search/facet", QUERY)
    r = d.get("results")
    if not isinstance(r, dict) or not isinstance(r.get("objects"), list): raise ValueError("response without results.objects")
    objs = r["objects"]
    if len(objs) < 20: raise ValueError(f"result suspiciously small ({len(objs)})")
    out = []
    for x in objs:
        if (x.get("city") or "").strip().lower() != CITY or x.get("entitytypeid") not in (1, None): continue
        street = (x.get("street") or "").strip() or None
        nr = " ".join(str(v) for v in (x.get("houseNumber"), x.get("houseNumberAddition")) if v)
        st, code = STATUS.get(x.get("status"), (f"status {x.get('status')}", f"status_{x.get('status')}"))
        bed = x.get("numberOfBedRooms")
        out.append(listing(
            slug=f"{PREFIX}{x['id']}", address=f"{street} {nr}".strip() if street else None, street=street,
            postcode=x.get("postalCode"), city=x.get("city"), lat=num(x.get("latitude")), lon=num(x.get("longitude")),
            type=x.get("entitysubtypelabel"), bedrooms=bed if isinstance(bed, int) and bed > 0 else None,
            m2=x.get("size"), rent=num(x.get("priceUnformatted")) or None, service=None,
            status=st, status_code=code,
            url=BASE + x["url"] if (x.get("url") or "").startswith("/") else x.get("url")))
    if not out: raise ValueError("0 Rotterdam listings in result")
    return out, "json_api", False, []
