"""Cinémathèque québécoise + Théâtre Outremont.

Both sit behind Cloudflare, which rate-limits or blocks some networks outright.
The adapter therefore:

  1. tries schema.org JSON-LD first (cheapest and most reliable when present);
  2. falls back to parsing French date + time pairs out of the page text;
  3. degrades gracefully — a venue it cannot reach is reported in status.json
     rather than failing the whole build.

`python3 scrapers/probe.py` dumps what these URLs actually return from the
current network, which is how to iterate on the parsers.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import time

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

VENUES = {
    "cinematheque": dict(
        venue=Venue(
            id="cinematheque", name="Cinémathèque québécoise", short_name="Cinémathèque",
            address="335 boulevard De Maisonneuve Est", neighbourhood="Quartier Latin",
            lat=45.5150, lng=-73.5610,
            url="https://www.cinematheque.qc.ca/fr/programme/",
            kind="repertory", source="cinematheque",
        ),
        listing=[
            "https://www.cinematheque.qc.ca/fr/programme/",
            "https://www.cinematheque.qc.ca/fr/programme/?page=2",
            "https://www.cinematheque.qc.ca/fr/programme/?page=3",
        ],
        detail_re=re.compile(r'href="(/fr/cinema/[a-z0-9-]+/)"'),
        origin="https://www.cinematheque.qc.ca",
    ),
    "outremont": dict(
        venue=Venue(
            id="outremont", name="Théâtre Outremont", short_name="Outremont",
            address="1248 avenue Bernard", neighbourhood="Outremont",
            lat=45.5197, lng=-73.6096,
            url="https://theatreoutremont.ca/",
            kind="repertory", source="cinematheque",
        ),
        listing=[
            "https://theatreoutremont.ca/programmation/",
            "https://theatreoutremont.ca/evenements/",
            "https://theatreoutremont.ca/",
        ],
        detail_re=re.compile(r'href="(https?://theatreoutremont\.ca/(?:evenement|spectacle|film)[^"]*)"'),
        origin="https://theatreoutremont.ca",
    ),
}

LD_RE = re.compile(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', re.S)

# "lundi 8 septembre 2026" / "8 septembre" / "8 sept. 2026"
DATE_RE = re.compile(
    r"(?:(?:lun|mar|mer|jeu|ven|sam|dim)[a-zé]*\.?\s+)?"
    r"(\d{1,2})\s+([a-zéûôA-ZÉÛÔ]{3,10})\.?(?:\s+(\d{4}))?",
    re.I,
)
TIME_RE = re.compile(r"\b(\d{1,2})\s*h\s*(\d{2})?\b", re.I)
MAX_DETAILS = 60


def _clean_text(html: str) -> str:
    h = re.sub(r"<svg.*?</svg>", " ", html, flags=re.S | re.I)
    h = re.sub(r"(?is)<(script|style|nav|header|footer)[^>]*>.*?</\1>", " ", h)
    return strip_html(h)


def _iter_ld(html: str):
    for blob in LD_RE.findall(html):
        try:
            data = json.loads(blob.strip())
        except Exception:
            continue
        stack = [data]
        while stack:
            node = stack.pop()
            if isinstance(node, list):
                stack.extend(node)
            elif isinstance(node, dict):
                if "@graph" in node:
                    stack.append(node["@graph"])
                yield node


def _from_ld(html: str, venue_id: str, page_url: str) -> list[Screening]:
    out: list[Screening] = []
    horizon = today() + dt.timedelta(days=150)
    for node in _iter_ld(html):
        types = node.get("@type") or ""
        types = [types] if isinstance(types, str) else list(types)
        if not any(t in {"ScreeningEvent", "Event", "TheaterEvent"} for t in types):
            continue
        start = clean(node.get("startDate"))
        if "T" not in start:
            continue
        date_s, _, rest = start.partition("T")
        time_s = rest[:5]
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_s) or not re.match(r"^\d{2}:\d{2}$", time_s):
            continue
        try:
            d = dt.date.fromisoformat(date_s)
        except ValueError:
            continue
        if d < today() or d > horizon:
            continue

        name = clean(node.get("name"))
        work = node.get("workPresented")
        if isinstance(work, dict) and work.get("name"):
            name = clean(work["name"])
        if not name:
            continue

        img = node.get("image")
        if isinstance(img, list):
            img = img[0] if img else ""
        if isinstance(img, dict):
            img = img.get("url", "")
        offers = node.get("offers")
        ticket = clean(offers.get("url")) if isinstance(offers, dict) else ""

        out.append(Screening(
            venue_id=venue_id, title=name,
            start=f"{date_s}T{time_s}", date=date_s, time=time_s,
            url=clean(node.get("url")) or page_url, ticket_url=ticket,
            synopsis=strip_html(node.get("description")), poster=clean(img),
            source="cinematheque",
        ))
    return out


def _from_text(html: str, venue_id: str, page_url: str) -> list[Screening]:
    """Fallback: pair French dates with times found nearby in the page text."""
    text = _clean_text(html)
    title_m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
    title = clean(strip_html(title_m.group(1))) if title_m else ""
    if not title:
        og = re.search(r'<meta property="og:title" content="([^"]+)"', html)
        title = clean(og.group(1)) if og else ""
    if not title:
        return []
    title = re.sub(r"\s*[|–-]\s*(Cinémathèque|Théâtre Outremont).*$", "", title).strip()

    poster = ""
    og_img = re.search(r'<meta property="og:image" content="([^"]+)"', html)
    if og_img:
        poster = og_img.group(1)
    desc = ""
    og_d = re.search(r'<meta property="og:description" content="([^"]+)"', html)
    if og_d:
        desc = clean(og_d.group(1))

    horizon = today() + dt.timedelta(days=150)
    seen = set()
    out: list[Screening] = []

    for dm in DATE_RE.finditer(text):
        day_s, mon_s, year_s = dm.groups()
        mon = month_from_name(mon_s)
        if not mon:
            continue
        window = text[dm.end(): dm.end() + 120]
        for tm in TIME_RE.finditer(window):
            h = int(tm.group(1))
            mi = int(tm.group(2) or 0)
            if not (0 <= h <= 23 and 0 <= mi <= 59):
                continue
            year = int(year_s) if year_s else today().year
            try:
                d = dt.date(year, mon, int(day_s))
            except ValueError:
                continue
            # Undated month/day in the past probably means next year.
            if not year_s and d < today():
                try:
                    d = dt.date(year + 1, mon, int(day_s))
                except ValueError:
                    continue
            if d < today() or d > horizon:
                continue
            key = (d.isoformat(), f"{h:02d}:{mi:02d}")
            if key in seen:
                continue
            seen.add(key)
            out.append(Screening(
                venue_id=venue_id, title=title,
                start=f"{d.isoformat()}T{h:02d}:{mi:02d}",
                date=d.isoformat(), time=f"{h:02d}:{mi:02d}",
                url=page_url, ticket_url=page_url,
                synopsis=desc, poster=poster, source="cinematheque",
            ))
    return out


def _fetch_venue(key: str, cfg: dict) -> list[Screening]:
    venue: Venue = cfg["venue"]
    found: list[Screening] = []
    detail_urls: list[str] = []
    last_err = None

    for url in cfg["listing"]:
        try:
            html = http_get(url, browser_ua=True, retries=2, timeout=30)
        except Exception as e:  # noqa: BLE001
            last_err = e
            continue
        found.extend(_from_ld(html, venue.id, url))
        for path in cfg["detail_re"].findall(html):
            full = path if path.startswith("http") else cfg["origin"] + path
            if full not in detail_urls:
                detail_urls.append(full)
        time.sleep(0.5)

    if found:
        return found

    for url in detail_urls[:MAX_DETAILS]:
        try:
            html = http_get(url, browser_ua=True, retries=1, timeout=30)
        except Exception as e:  # noqa: BLE001
            last_err = e
            continue
        got = _from_ld(html, venue.id, url) or _from_text(html, venue.id, url)
        found.extend(got)
        time.sleep(0.6)

    if not found and last_err:
        raise RuntimeError(str(last_err))
    return found


def fetch() -> tuple[list[Venue], list[Screening]]:
    venues: list[Venue] = []
    screenings: list[Screening] = []
    problems = []

    for key, cfg in VENUES.items():
        try:
            got = _fetch_venue(key, cfg)
        except Exception as e:  # noqa: BLE001
            got, err = [], e
            problems.append(f"{key}: {e}")
        else:
            err = None
        if got:
            venues.append(cfg["venue"])
            screenings.extend(got)
            log(f"[cinematheque] {cfg['venue'].short_name}: {len(got)} showtimes")
        else:
            if err is None:
                problems.append(f"{key}: no showtimes parsed")
            log(f"[cinematheque] {cfg['venue'].short_name}: unavailable")

    if not screenings:
        raise RuntimeError("; ".join(problems) or "no showtimes")
    return venues, screenings
