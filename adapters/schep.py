"""Schep Vastgoedmanagers: Realmark MarketSuite JSON API behind the search page,
server-side filtered on location. One request per check (~350 KB), so every ~6 min."""
from .common import get_json, listing

KEY, NAME, PREFIX, EVERY_S = "schep", "Schep Vastgoedmanagers", "schep:", 360
BASE = "https://zoeken.schepvastgoedmanagers.nl"
CITY = "Rotterdam"

def fetch():
    out, page, last = [], 1, 1
    while page <= last and page <= 5:
        d = get_json(f"{BASE}/api/ms/listing/properties?perPage=100&page={page}&sort=-published_at"
                     f"&filter%5Bimport_type%5D=RentResident&filter%5Blocation%5D={CITY}")
        if "data" not in d: raise ValueError("response without 'data'")
        last = (d.get("meta") or {}).get("last_page") or 1
        for x in d["data"]:
            a = x.get("address") or {}; h = x.get("handover") or {}; ch = x.get("characteristic") or {}
            lay = ch.get("layout") or {}; st = x.get("status") or {}
            svc = h.get("service_costs")
            out.append(listing(
                slug=PREFIX + x["slug"], address=x.get("title"), street=a.get("street"),
                postcode=a.get("postal_code"), city=(a.get("location") or "").title() or None,
                lat=a.get("position_lat"), lon=a.get("position_long"), type=ch.get("type"),
                rooms=lay.get("number_of_rooms") or None, bedrooms=lay.get("number_of_bedrooms") or None,
                m2=ch.get("living_area"), rent=h.get("price"), service=svc,
                status=st.get("label"), status_code=st.get("code"), energy_label=ch.get("energy_label"),
                published=x.get("published_at_date"), available=x.get("available_at_label"),
                inquiries=(x.get("statistics") or {}).get("inquiries"),
                url=f"{BASE}/huur/woningen/{x['slug']}"))
        page += 1
    return out, "json_api", False, []
