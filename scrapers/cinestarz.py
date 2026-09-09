"""Ciné Starz — discount cinemas around Montréal (Théâtre Toolkit platform).

Server-rendered HTML. Each location page shows one day at a time; the date
picker uses a ?date=YYYY-MM-DD query string.
"""

from __future__ import annotations

import datetime as dt
import re
import time

from common import Screening, Venue, clean, http_get, log, parse_time, today

BASE = "https://www.cinestarz.ca"
DAYS_AHEAD = 7

# Greater-Montréal locations only (their Ontario sites are excluded).
LOCATIONS = {
    "cotedesneiges": dict(id="starz-cdn", name="Ciné Starz Côte-des-Neiges", short="Starz CDN",
                          address="6900 chemin de la Côte-des-Neiges", city="Montréal",
                          neighbourhood="Côte-des-Neiges", lat=45.4948, lng=-73.6320),
    "deluxecavendish": dict(id="starz-cavendish", name="Ciné Starz Deluxe Cavendish", short="Starz Cavendish",
                            address="5800 boulevard Cavendish", city="Côte-Saint-Luc",
                            neighbourhood="Côte-Saint-Luc", lat=45.4713, lng=-73.6560),
    "deluxesources": dict(id="starz-sources", name="Ciné Starz Deluxe Des Sources", short="Starz Des Sources",
                          address="3237 boulevard des Sources", city="Dollard-des-Ormeaux",
                          neighbourhood="West Island", lat=45.4885, lng=-73.8022),
    "lacordaire": dict(id="starz-lacordaire", name="Ciné Starz Lacordaire", short="Starz Lacordaire",
                       address="4200 boulevard Lacordaire", city="Montréal",
                       neighbourhood="Saint-Léonard", lat=45.5883, lng=-73.5940),
    "stlaurentcentre": dict(id="starz-stlaurent", name="Ciné Starz Saint-Laurent", short="Starz Saint-Laurent",
                            address="1200 rue du Marché-Central", city="Montréal",
                            neighbourhood="Saint-Laurent", lat=45.5390, lng=-73.6600),
    "longueuil": dict(id="starz-longueuil", name="Ciné Starz Longueuil", short="Starz Longueuil",
                      address="825 rue Saint-Laurent Ouest", city="Longueuil",
                      neighbourhood="Rive-Sud", lat=45.5330, lng=-73.5180),
    "taschereau": dict(id="starz-taschereau", name="Ciné Starz Taschereau", short="Starz Taschereau",
                       address="705 boulevard Taschereau", city="Brossard",
                       neighbourhood="Rive-Sud", lat=45.4900, lng=-73.4700),
}

CARD_RE = re.compile(
    r'<h3 class="nowPlaying__movieTitle"(.*?)(?=<h3 class="nowPlaying__movieTitle"|<footer|</main)', re.S
)
TITLE_RE = re.compile(r'<a class="nowPlaying__movieLink" href="([^"]*)"[^>]*>(.*?)</a>', re.S)
POSTER_RE = re.compile(r'<img data-src="([^"]+)"')
RUNTIME_RE = re.compile(r'movieInfo__text--runtime">\s*([\d]+)\s*\n?\s*min', re.S)
RATING_RE = re.compile(r'movieInfo__text--rating">\s*([^<]*?)\s*</span>', re.S)
AMENITY_RE = re.compile(r'nowPlaying__amenityName">\s*<span>([^<]*)</span>', re.S)
TIME_RE = re.compile(r'button--showtime[^"]*"[^>]*>\s*(?:<a[^>]*href="([^"]*)"[^>]*>)?\s*<span>([^<]+)</span>', re.S)


def _venues() -> list[Venue]:
    return [
        Venue(
            id=v["id"], name=v["name"], short_name=v["short"], address=v["address"],
            city=v["city"], neighbourhood=v["neighbourhood"], lat=v["lat"], lng=v["lng"],
            url=f"{BASE}/movie-theater/{slug}", chain="cinestarz", kind="multiplex",
            source="cinestarz",
        )
        for slug, v in LOCATIONS.items()
    ]


def _parse_day(html: str, meta: dict, day: dt.date) -> list[Screening]:
    out: list[Screening] = []
    for card in CARD_RE.findall(html):
        tm = TITLE_RE.search(card)
        if not tm:
            continue
        href, title = tm.group(1), clean(tm.group(2))
        if not title:
            continue
        film_url = href if href.startswith("http") else f"{BASE}{href}"
        pm = POSTER_RE.search(card)
        poster = pm.group(1) if pm else ""
        rt = RUNTIME_RE.search(card)
        runtime = int(rt.group(1)) if rt else None
        rr = RATING_RE.search(card)
        rating = clean(rr.group(1)) if rr and clean(rr.group(1)) != "N/A" else ""

        amenity = AMENITY_RE.search(card)
        fmt = clean(amenity.group(1)) if amenity else ""
        if fmt.lower() in {"regular", "régulier"}:
            fmt = "2D"

        # Version hints live in these all-caps titles (e.g. "MAL.ENG.SUB").
        version = ""
        up = title.upper()
        if "ENG.SUB" in up or "ENG SUB" in up:
            version = "VOSTA"
        elif re.search(r"\bV\.?F\.?\b|FRENCH", up):
            version = "VF"

        for ticket_href, raw_time in TIME_RE.findall(card):
            hm = parse_time(clean(raw_time))
            if not hm:
                continue
            out.append(
                Screening(
                    venue_id=meta["id"],
                    title=title,
                    start=f"{day.isoformat()}T{hm[0]:02d}:{hm[1]:02d}",
                    date=day.isoformat(),
                    time=f"{hm[0]:02d}:{hm[1]:02d}",
                    url=film_url,
                    ticket_url=(ticket_href if ticket_href.startswith("http")
                                else f"{BASE}{ticket_href}") if ticket_href else film_url,
                    version_raw=version,
                    fmt=fmt,
                    runtime=runtime,
                    rating=rating,
                    poster=poster,
                    source="cinestarz",
                )
            )
    return out


def fetch() -> tuple[list[Venue], list[Screening]]:
    screenings: list[Screening] = []
    start = today()
    for slug, meta in LOCATIONS.items():
        got = 0
        for offset in range(DAYS_AHEAD):
            day = start + dt.timedelta(days=offset)
            url = f"{BASE}/movie-theater/{slug}"
            if offset:
                url += f"?date={day.isoformat()}"
            try:
                html = http_get(url, browser_ua=True)
            except Exception as e:  # noqa: BLE001
                log(f"[cinestarz] {slug} {day}: {e}")
                continue
            found = _parse_day(html, meta, day)
            screenings.extend(found)
            got += len(found)
            if offset == 0 and not found:
                break  # location likely closed / no listings
            time.sleep(0.2)
        log(f"[cinestarz] {meta['short']}: {got}")
    return _venues(), screenings
