"""Hef Wonen: server-rendered page with embedded Nuxt payload (sandboxed node vm); HTML-card fallback.
Slugs are unprefixed (legacy state)."""
import html as htmlmod, json, re, subprocess
from .common import request, listing, num

KEY, NAME, PREFIX, EVERY_S = "hef", "Hef Wonen", "", 120
URL = "https://huuraanbod.hefwonen.nl/huuraanbod"

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
            out.append(listing(slug=x["slug"], category=cat, address=x.get("title"), street=a.get("street"),
                               postcode=a.get("postal_code"), city=(a.get("location") or "").title() or None,
                               lat=a.get("position_lat"), lon=a.get("position_long"), type=ch.get("type"),
                               rooms=lay.get("number_of_rooms") or None, bedrooms=lay.get("number_of_bedrooms") or None,
                               m2=ch.get("living_area"), rent=h.get("price"), service=h.get("service_costs") or 0,
                               status=st.get("label"), status_code=st.get("code"), energy_label=ch.get("energy_label"),
                               published=x.get("published_at_date"), available=x.get("available_at_label"),
                               inquiries=(x.get("statistics") or {}).get("inquiries"), url=f"{URL}/{x['slug']}"))
    return out

def parse_cards(page):
    out = []
    for card in page.split('class="property"')[1:]:
        m = re.search(r'href="/huuraanbod/([^"]+)"', card)
        if not m: continue
        t = lambda pat: (lambda r: htmlmod.unescape(r.group(1)).strip() if r else None)(re.search(pat, card, re.S))
        title = t(r'property__title[^>]*>([^<]+)<')
        loc = re.search(r'property__location[^>]*><span[^>]*>([^<]*)</span><span[^>]*>([^<]*)<', card)
        pr = {k.strip(): num(re.sub(r"[^\d,]", "", v)) for k, v in re.findall(r'<span[^>]*>([^<]+)</span><span class="highlighted[^>]*>([^<]+)<', card)}
        m2 = re.search(r'>(\d+)\s*m²<', card); rooms = re.search(r'details__rooms.*?<span[^>]*>(\d+)', card, re.S)
        out.append(listing(slug=m.group(1), category="rent?", address=title,
                           street=re.sub(r"\s+\d.*$", "", title or "") or None,
                           postcode=loc.group(1).strip(" ,") if loc else None,
                           city=loc.group(2).strip().title() if loc else None,
                           rooms=int(rooms.group(1)) if rooms else None, m2=int(m2.group(1)) if m2 else None,
                           rent=pr.get("Huurprijs p.m."), service=pr.get("Servicekosten p.m.") or 0,
                           status=t(r'property__label"[^>]*>([^<]+)<') or "Beschikbaar?", url=f"{URL}/{m.group(1)}"))
    return out

def fetch():
    """Returns (listings, source, partial, warnings)."""
    page = request(URL, attempts=3)
    warn = [m for m in ("window.__NUXT__", "property__title", "/huuraanbod/") if m not in page]
    try:
        return parse_payload(page), "nuxt_payload", False, warn
    except Exception as e:
        return parse_cards(page), "html_cards_fallback", True, warn + [f"payload: {e}"]
