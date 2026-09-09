"""Static, crawlable pages for films, cinemas and themes.

The app itself is a single JS-rendered page, so a crawler sees a search box and
nothing else. These pages give every film, cinema and theme a permanent URL
with real content and schema.org data, and each one links into the app.

They are generated at build time from the same payload the app consumes, so
they can never drift from it.
"""

from __future__ import annotations

import datetime as dt
import html
import json
import os
import re
import unicodedata

SITE = "https://mtlmovies.github.io"
NAME = "Montréal Cinéma"


def slugify(s: str, maxlen: int = 60) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return (s[:maxlen].strip("-") or "film")


def e(s) -> str:
    return html.escape(str(s if s is not None else ""), quote=True)


def runtime_str(m) -> str:
    if not m:
        return ""
    h, r = divmod(int(m), 60)
    return f"{h}h {r:02d}m" if h else f"{r}m"


def iso_duration(m) -> str:
    if not m:
        return ""
    h, r = divmod(int(m), 60)
    return f"PT{h}H{r}M" if h else f"PT{r}M"


# ---------------------------------------------------------------------------
# shell
# ---------------------------------------------------------------------------

def shell(*, title, description, canonical, body, jsonld=None, lang="fr-CA") -> str:
    ld = ""
    if jsonld:
        ld = ('<script type="application/ld+json">'
              + json.dumps(jsonld, ensure_ascii=False, separators=(",", ":"))
              + "</script>")
    return f"""<!doctype html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(description)}">
<link rel="canonical" href="{e(canonical)}">
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(description)}">
<meta property="og:url" content="{e(canonical)}">
<meta property="og:type" content="website">
<meta name="theme-color" content="#08080a">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Ctext y='26' font-size='26'%3E%F0%9F%8E%9E%EF%B8%8F%3C/text%3E%3C/svg%3E">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap">
<link rel="stylesheet" href="{SITE}/styles.css">
{ld}
<style>
  .page {{ max-width: 940px; margin: 0 auto; padding: 90px var(--pad) 80px; }}
  .page h1 {{ font-size: clamp(28px,4.6vw,48px); letter-spacing:-.04em; margin-bottom:12px; }}
  .page h2 {{ font-size: 19px; margin: 34px 0 12px; }}
  .crumbs {{ font-size:12.5px; color:var(--text-3); margin-bottom:22px; }}
  .crumbs a {{ color:var(--text-2); }}
  .lede {{ color:var(--text-2); font-size:16px; line-height:1.65; max-width:70ch; }}
  .kv {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:14px 24px;
         padding:18px 0; border-top:1px solid var(--line); margin-top:22px; }}
  .kv dt {{ font-size:9.5px; font-weight:750; letter-spacing:.1em; text-transform:uppercase; color:var(--text-3); }}
  .kv dd {{ margin:4px 0 0; font-size:14.5px; }}
  .sched {{ border-top:1px solid var(--line); padding:14px 0; }}
  .sched h3 {{ font-size:14.5px; margin-bottom:8px; }}
  .sched .day {{ display:grid; grid-template-columns:150px 1fr; gap:12px; padding:5px 0;
                 border:0; background:none; text-align:left; }}
  .sched .day b {{ font-weight:600; font-size:12.5px; color:var(--text-3); }}
  .tl {{ display:flex; flex-wrap:wrap; gap:6px; }}
  .tl a, .tl span {{ font-size:13px; font-weight:700; font-variant-numeric:tabular-nums;
        padding:5px 10px; border-radius:6px; border:1px solid var(--line); background:var(--surface); }}
  .tl a:hover {{ border-color:var(--text); background:var(--text); color:var(--bg); }}
  .cols {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(230px,1fr)); gap:10px 18px; }}
  .cols a {{ color:var(--text-2); font-size:14px; padding:5px 0; display:block; }}
  .cols a:hover {{ color:var(--text); }}
  .poster-lead {{ display:grid; grid-template-columns:180px 1fr; gap:26px; align-items:start; }}
  .poster-lead img {{ border-radius:var(--r); width:100%; }}
  @media (max-width:640px) {{ .poster-lead {{ grid-template-columns:1fr; }}
    .sched .day {{ grid-template-columns:1fr; }} }}
  .backlink {{ display:inline-flex; gap:8px; align-items:center; margin-bottom:26px;
        font-size:13px; font-weight:600; color:var(--text-2); }}
  .backlink:hover {{ color:var(--text); }}
</style>
</head>
<body>
<div class="page">
<a class="backlink" href="{SITE}/">← {e(NAME)}</a>
{body}
</div>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# film pages
# ---------------------------------------------------------------------------

def film_page(m: dict, venues: dict, out_dir: str):
    slug = m["slug"]
    title = m["title"]
    year = m.get("year")
    director = m.get("director") or ""
    shows = sorted(m["showtimes"], key=lambda s: s["start"])
    vnames = []
    for s in shows:
        v = venues.get(s["venue"])
        if v and v["name"] not in vnames:
            vnames.append(v["name"])

    head = f"{title}" + (f" ({year})" if year else "")
    desc = (f"{head} — showtimes in Montréal"
            + (f", directed by {director}" if director else "")
            + (f". Playing at {', '.join(vnames[:3])}" if vnames else "")
            + f". {len(shows)} screening{'s' if len(shows) != 1 else ''} listed.")

    by_venue: dict[str, list] = {}
    for s in shows:
        by_venue.setdefault(s["venue"], []).append(s)

    blocks = []
    for vid, sts in by_venue.items():
        v = venues.get(vid, {"name": vid, "address": ""})
        by_day: dict[str, list] = {}
        for s in sts:
            by_day.setdefault(s["date"], []).append(s)
        days = "".join(
            f'<div class="day"><b>{e(d)}</b><div class="tl">' +
            "".join(
                (f'<a href="{e(s.get("ticket_url") or s.get("url") or "#")}" rel="nofollow noopener" target="_blank">{e(s["time"])}</a>'
                 if (s.get("ticket_url") or s.get("url")) else f'<span>{e(s["time"])}</span>')
                for s in ss
            ) + "</div></div>"
            for d, ss in by_day.items()
        )
        blocks.append(
            f'<div class="sched"><h3><a href="{SITE}/cinema/{e(v.get("slug", vid))}/">{e(v["name"])}</a></h3>'
            f'<div style="font-size:12.5px;color:var(--text-3);margin-bottom:8px">{e(v.get("address", ""))}</div>'
            f"{days}</div>"
        )

    facts = []
    for k, val in (("Year", year), ("Runtime", runtime_str(m.get("runtime"))),
                   ("Director", director), ("Cast", m.get("cast")),
                   ("Country", m.get("country")),
                   ("Genre", ", ".join(m.get("genres") or [])),
                   ("Letterboxd", m.get("letterboxd_rating")),
                   ("IMDb", m.get("imdb_rating"))):
        if val:
            facts.append(f"<div><dt>{e(k)}</dt><dd>{e(val)}</dd></div>")

    tags = " · ".join(sorted(set(m.get("tags") or [])))
    poster = m.get("poster") or ""

    body = f"""
<div class="crumbs"><a href="{SITE}/">{e(NAME)}</a> / <a href="{SITE}/films/">Films</a> / {e(title)}</div>
<div class="poster-lead">
  <div>{f'<img src="{e(poster)}" alt="{e(title)} poster" width="180" loading="lazy">' if poster else ''}</div>
  <div>
    <h1>{e(title)}</h1>
    <p class="lede">{e(m.get('synopsis') or desc)}</p>
    {f'<p class="lede" style="margin-top:10px;font-size:13px;color:var(--text-3)">{e(tags)}</p>' if tags else ''}
    <dl class="kv">{''.join(facts)}</dl>
  </div>
</div>
<h2>Showtimes in Montréal</h2>
{''.join(blocks) or '<p class="lede">No screenings currently listed.</p>'}
<p style="margin-top:26px"><a class="backlink" href="{SITE}/#film={e(m['id'])}">Open in the showtimes app →</a></p>
"""

    ld = {
        "@context": "https://schema.org",
        "@type": "Movie",
        "name": title,
        "url": f"{SITE}/movie/{slug}/",
    }
    if poster:
        ld["image"] = poster
    if m.get("synopsis"):
        ld["description"] = m["synopsis"][:900]
    if director:
        ld["director"] = {"@type": "Person", "name": director.split(",")[0].strip()}
    if year:
        ld["datePublished"] = str(year)
    if m.get("runtime"):
        ld["duration"] = iso_duration(m["runtime"])
    if m.get("genres"):
        ld["genre"] = m["genres"]
    if m.get("letterboxd_rating"):
        ld["aggregateRating"] = {"@type": "AggregateRating", "ratingValue": m["letterboxd_rating"],
                                 "bestRating": 5, "worstRating": 0,
                                 "ratingCount": m.get("letterboxd_votes") or 1}
    events = []
    for s in shows[:60]:
        v = venues.get(s["venue"])
        if not v:
            continue
        ev = {
            "@type": "ScreeningEvent",
            "name": f"{title} — {v['name']}",
            "startDate": s["start"],
            "location": {"@type": "MovieTheater", "name": v["name"],
                         "address": {"@type": "PostalAddress",
                                     "streetAddress": v.get("address", ""),
                                     "addressLocality": v.get("city", "Montréal"),
                                     "addressRegion": "QC", "addressCountry": "CA"}},
            "workPresented": {"@type": "Movie", "name": title,
                              "url": f"{SITE}/movie/{slug}/"},
        }
        if s.get("ticket_url") or s.get("url"):
            ev["offers"] = {"@type": "Offer", "url": s.get("ticket_url") or s["url"]}
        events.append(ev)

    graph = [ld] + events
    d = os.path.join(out_dir, "movie", slug)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "index.html"), "w", encoding="utf-8") as f:
        f.write(shell(title=f"{head} — showtimes in Montréal | {NAME}",
                      description=desc[:300], canonical=f"{SITE}/movie/{slug}/",
                      body=body, jsonld={"@context": "https://schema.org", "@graph": graph},
                      lang="en-CA"))


# ---------------------------------------------------------------------------
# cinema pages
# ---------------------------------------------------------------------------

def cinema_page(v: dict, movies: list, out_dir: str):
    slug = v["slug"]
    mine = []
    for m in movies:
        sts = [s for s in m["showtimes"] if s["venue"] == v["id"]]
        if sts:
            mine.append((m, sorted(sts, key=lambda s: s["start"])))
    mine.sort(key=lambda x: x[1][0]["start"])

    kind = {"repertory": "repertory cinema", "museum": "museum cinema",
            "multiplex": "multiplex"}.get(v.get("kind"), "cinema")
    desc = (f"{v['name']} — {kind} at {v.get('address','')}, "
            f"{v.get('city','Montréal')}. {len(mine)} film"
            f"{'s' if len(mine) != 1 else ''} currently listed with showtimes.")

    rows = []
    for m, sts in mine:
        by_day: dict[str, list] = {}
        for s in sts:
            by_day.setdefault(s["date"], []).append(s)
        days = "".join(
            f'<div class="day"><b>{e(d)}</b><div class="tl">' +
            "".join(f'<span>{e(s["time"])}</span>' for s in ss) + "</div></div>"
            for d, ss in list(by_day.items())[:8])
        rows.append(
            f'<div class="sched"><h3><a href="{SITE}/movie/{e(m["slug"])}/">{e(m["title"])}</a>'
            f'{f" <span style=\'color:var(--text-3);font-weight:500\'>{e(m["year"])}</span>" if m.get("year") else ""}</h3>{days}</div>')

    facts = []
    for k, val in (("Address", v.get("address")), ("City", v.get("city")),
                   ("Neighbourhood", v.get("neighbourhood")), ("Type", kind),
                   ("Films listed", len(mine))):
        if val:
            facts.append(f"<div><dt>{e(k)}</dt><dd>{e(val)}</dd></div>")

    body = f"""
<div class="crumbs"><a href="{SITE}/">{e(NAME)}</a> / <a href="{SITE}/cinemas/">Cinemas</a> / {e(v['name'])}</div>
<h1>{e(v['name'])}</h1>
<p class="lede">{e(desc)}</p>
<dl class="kv">{''.join(facts)}</dl>
<h2>What's playing</h2>
{''.join(rows) or '<p class="lede">No screenings currently listed.</p>'}
<p style="margin-top:26px"><a class="backlink" href="{SITE}/">Browse all Montréal showtimes →</a></p>
"""
    ld = {
        "@context": "https://schema.org",
        "@type": "MovieTheater",
        "name": v["name"],
        "url": f"{SITE}/cinema/{slug}/",
        "address": {"@type": "PostalAddress", "streetAddress": v.get("address", ""),
                    "addressLocality": v.get("city", "Montréal"),
                    "addressRegion": "QC", "addressCountry": "CA"},
    }
    if v.get("lat") and v.get("lng"):
        ld["geo"] = {"@type": "GeoCoordinates", "latitude": v["lat"], "longitude": v["lng"]}
    if v.get("url"):
        ld["sameAs"] = v["url"]

    d = os.path.join(out_dir, "cinema", slug)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "index.html"), "w", encoding="utf-8") as f:
        f.write(shell(title=f"{v['name']} — showtimes | {NAME}", description=desc[:300],
                      canonical=f"{SITE}/cinema/{slug}/", body=body, jsonld=ld, lang="en-CA"))


# ---------------------------------------------------------------------------
# theme + index pages
# ---------------------------------------------------------------------------

THEMES = [
    ("35mm", "35 mm & 16 mm film screenings in Montréal",
     lambda m: "celluloid" in (m.get("tags") or []),
     "Every screening projected from film — 35 mm, 16 mm and 70 mm prints — in Montréal cinemas."),
    ("classics", "Classic films playing in Montréal cinemas",
     lambda m: "classic" in (m.get("tags") or []),
     "Older films back on a Montréal screen: repertory programming, retrospectives and revivals."),
    ("restorations", "Restored films playing in Montréal",
     lambda m: "restoration" in (m.get("tags") or []),
     "New restorations and remastered prints screening in Montréal."),
    ("repertory", "Repertory cinema in Montréal",
     lambda m: "repertory" in (m.get("tags") or []),
     "What Montréal's repertory houses and cinematheques are showing."),
]


def theme_page(slug, title, movies, blurb, out_dir):
    items = "".join(
        f'<div class="sched"><h3><a href="{SITE}/movie/{e(m["slug"])}/">{e(m["title"])}</a>'
        f'{f" <span style=\'color:var(--text-3);font-weight:500\'>{e(m["year"])}</span>" if m.get("year") else ""}</h3>'
        f'<div style="font-size:12.5px;color:var(--text-3)">'
        f'{e(", ".join(sorted({s["venue"] for s in m["showtimes"]})[:4]))} · '
        f'{len(m["showtimes"])} screening{"s" if len(m["showtimes"]) != 1 else ""}</div></div>'
        for m in movies[:120])
    body = f"""
<div class="crumbs"><a href="{SITE}/">{e(NAME)}</a> / {e(title)}</div>
<h1>{e(title)}</h1>
<p class="lede">{e(blurb)}</p>
<h2>{len(movies)} film{'s' if len(movies) != 1 else ''}</h2>
{items or '<p class="lede">Nothing listed right now.</p>'}
<p style="margin-top:26px"><a class="backlink" href="{SITE}/">Browse all Montréal showtimes →</a></p>
"""
    d = os.path.join(out_dir, slug)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "index.html"), "w", encoding="utf-8") as f:
        f.write(shell(title=f"{title} | {NAME}", description=blurb,
                      canonical=f"{SITE}/{slug}/", body=body, lang="en-CA"))


def index_page(kind, title, links, blurb, out_dir):
    body = f"""
<div class="crumbs"><a href="{SITE}/">{e(NAME)}</a> / {e(title)}</div>
<h1>{e(title)}</h1>
<p class="lede">{e(blurb)}</p>
<h2>{len(links)} entries</h2>
<div class="cols">{''.join(f'<a href="{e(u)}">{e(n)}</a>' for n, u in links)}</div>
"""
    d = os.path.join(out_dir, kind)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "index.html"), "w", encoding="utf-8") as f:
        f.write(shell(title=f"{title} | {NAME}", description=blurb,
                      canonical=f"{SITE}/{kind}/", body=body, lang="en-CA"))


# ---------------------------------------------------------------------------

def build(payload: dict, out_dir: str) -> int:
    venues = {v["id"]: v for v in payload["venues"]}
    for v in venues.values():
        v["slug"] = slugify(v["name"])

    seen: set[str] = set()
    for m in payload["movies"]:
        base = slugify(m["title"]) + (f"-{m['year']}" if m.get("year") else "")
        slug, n = base, 2
        while slug in seen:
            slug = f"{base}-{n}"
            n += 1
        seen.add(slug)
        m["slug"] = slug

    n = 0
    for m in payload["movies"]:
        film_page(m, venues, out_dir)
        n += 1
    for v in venues.values():
        cinema_page(v, payload["movies"], out_dir)
        n += 1

    for slug, title, pred, blurb in THEMES:
        theme_page(slug, title, [m for m in payload["movies"] if pred(m)], blurb, out_dir)
        n += 1

    index_page("films", "All films playing in Montréal",
               [(m["title"], f"{SITE}/movie/{m['slug']}/") for m in
                sorted(payload["movies"], key=lambda x: x["title"])],
               "Every film with a listed screening in Greater Montréal.", out_dir)
    index_page("cinemas", "Montréal cinemas",
               [(v["name"], f"{SITE}/cinema/{v['slug']}/") for v in
                sorted(venues.values(), key=lambda x: x["name"])],
               "Every cinema this index covers, from repertory houses to multiplexes.", out_dir)
    n += 2

    urls = [f"{SITE}/", f"{SITE}/films/", f"{SITE}/cinemas/"]
    urls += [f"{SITE}/{s}/" for s, *_ in THEMES]
    urls += [f"{SITE}/movie/{m['slug']}/" for m in payload["movies"]]
    urls += [f"{SITE}/cinema/{v['slug']}/" for v in venues.values()]
    today = dt.date.today().isoformat()
    with open(os.path.join(out_dir, "sitemap.xml"), "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n'
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n')
        for u in urls:
            f.write(f"<url><loc>{e(u)}</loc><lastmod>{today}</lastmod></url>\n")
        f.write("</urlset>\n")
    with open(os.path.join(out_dir, "robots.txt"), "w", encoding="utf-8") as f:
        f.write(f"User-agent: *\nAllow: /\nSitemap: {SITE}/sitemap.xml\n")

    return n


if __name__ == "__main__":
    # Regenerate the static pages from whatever data/ currently holds, without
    # scraping. Deploys triggered by a code push take this path.
    import shutil
    import sys

    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    src = os.path.join(root, "data", "index.json")
    dst = os.path.join(root, "pages")
    try:
        with open(src, encoding="utf-8") as fh:
            payload = json.load(fh)
    except Exception as exc:  # noqa: BLE001
        print(f"pages: no dataset to render ({exc})", file=sys.stderr)
        raise SystemExit(0)

    shutil.rmtree(dst, ignore_errors=True)
    os.makedirs(dst, exist_ok=True)
    print(f"pages: generated {build(payload, dst)} files")
