"""Cinémas Guzzo — Méga-Plex Terrebonne 14 (their remaining location).

Static server-rendered HTML. Each film block lists one or more
"<day> : <time>-<time>-..." groups, optionally preceded by a version header.
The page header gives the week the schedule covers, which is how we turn day
names into real dates.
"""

from __future__ import annotations

import datetime as dt
import re

from common import (
    Screening,
    Venue,
    clean,
    http_get,
    log,
    month_from_name,
    parse_time,
    strip_html,
    today,
)

BASE = "https://www.cinemasguzzo.com"
INDEX = f"{BASE}/cinemas.html"

FR_DAYS = {
    "lundi": 0, "mardi": 1, "mercredi": 2, "jeudi": 3,
    "vendredi": 4, "samedi": 5, "dimanche": 6,
}

VENUE = Venue(
    id="guzzo-terrebonne",
    name="Cinémas Guzzo — Méga-Plex Terrebonne 14",
    short_name="Guzzo Terrebonne",
    address="1071 chemin du Coteau",
    city="Terrebonne",
    neighbourhood="Terrebonne",
    lat=45.708031, lng=-73.650621,
    url=f"{BASE}/5-cinemas-horaire-mega-plex-terrebonne-14.html",
    chain="guzzo", kind="multiplex", source="guzzo",
)

LISTING_RE = re.compile(r'<div class="listing hoverFilm">(.*?)(?=<div class="listing hoverFilm">|<div id="bas)', re.S)
H2_RE = re.compile(r"<h2>\s*<a[^>]*href=\"([^\"]*)\"[^>]*>(.*?)</a>", re.S)
POSTER_RE = re.compile(r'<img src="(DATA/FILM/[^"]+)"')
P_RE = re.compile(r"<p([^>]*)>(.*?)</p>", re.S)
RANGE_RE = re.compile(
    r"Horaire\s+du\s+(\d{1,2})\s*(?:([A-Za-zÀ-ÿ.]+)\s*)?au\s+(\d{1,2})\s+([A-Za-zÀ-ÿ.]+)\.?\s+(\d{4})",
    re.S | re.I,
)


def _week_dates(html: str) -> dict[int, dt.date]:
    """Map weekday index -> date, from the 'Horaire du X au Y mois ANNEE' header."""
    text = strip_html(html)
    m = RANGE_RE.search(text)
    start = None
    if m:
        d1, mon1, d2, mon2, year = m.groups()
        month2 = month_from_name(mon2)
        month1 = month_from_name(mon1) if mon1 else month2
        try:
            start = dt.date(int(year), month1 or month2, int(d1))
        except (ValueError, TypeError):
            start = None
    if not start:
        # Fall back to the current week starting today.
        start = today()

    out = {}
    for i in range(8):
        d = start + dt.timedelta(days=i)
        out.setdefault(d.weekday(), d)
    return out


def _find_cinema_pages() -> list[str]:
    try:
        html = http_get(INDEX, browser_ua=True)
    except Exception as e:  # noqa: BLE001
        log(f"[guzzo] index: {e}")
        return [VENUE.url]
    pages = re.findall(r'href="((?:https?://[^"]*)?\d+-cinemas-horaire-[a-z0-9-]+\.html)"', html)
    urls = []
    for p in dict.fromkeys(pages):
        urls.append(p if p.startswith("http") else f"{BASE}/{p.lstrip('/')}")
    return urls or [VENUE.url]


def fetch() -> tuple[list[Venue], list[Screening]]:
    screenings: list[Screening] = []
    for url in _find_cinema_pages():
        try:
            html = http_get(url, browser_ua=True)
        except Exception as e:  # noqa: BLE001
            log(f"[guzzo] {url}: {e}")
            continue

        week = _week_dates(html)

        for block in LISTING_RE.findall(html):
            h2 = H2_RE.search(block)
            if not h2:
                continue
            film_path, title = h2.group(1), clean(h2.group(2))
            if not title:
                continue
            film_url = film_path if film_path.startswith("http") else f"{BASE}/{film_path.lstrip('/')}"
            pm = POSTER_RE.search(block)
            poster = f"{BASE}/{pm.group(1)}" if pm else ""

            version = "VF"  # Guzzo programmes in French unless flagged otherwise
            current_day = None

            for attrs, body in P_RE.findall(block):
                text = clean(body)
                if not text:
                    continue
                low = text.lower().rstrip(" :")

                if "<strong>" in body or "<b>" in body and "version" in low:
                    if "version" in low:
                        version = "VOA" if "anglais" in low else "VF"
                        continue

                if low.rstrip(" :") in FR_DAYS:
                    current_day = FR_DAYS[low.rstrip(" :")]
                    continue

                if re.match(r"^[\d:h\-\s,]+$", text) and re.search(r"\d", text):
                    if current_day is None:
                        continue
                    day_date = week.get(current_day)
                    if not day_date or day_date < today():
                        continue
                    for chunk in re.split(r"[-,]", text):
                        hm = parse_time(chunk.strip())
                        if not hm:
                            continue
                        screenings.append(
                            Screening(
                                venue_id=VENUE.id,
                                title=title,
                                start=f"{day_date.isoformat()}T{hm[0]:02d}:{hm[1]:02d}",
                                date=day_date.isoformat(),
                                time=f"{hm[0]:02d}:{hm[1]:02d}",
                                url=film_url,
                                ticket_url=film_url,
                                version_raw=version,
                                poster=poster,
                                source="guzzo",
                            )
                        )
    log(f"[guzzo] {len(screenings)} showtimes")
    return [VENUE], screenings
