"""Cinémathèque québécoise.

Their programme page carries the showtimes after all — not in the visible card
(which shows only a date range) but inside the per-film ticket modal that the
"Billets" button opens. Each modal holds the film's title and one link per
screening, and the ticketing URL carries the exact date:

    .../cinematheque/?schdate=2026-09-10&perfix=14272
    <span>jeudi</span> 10 septembre 2026<br>à 17:00

Film detail pages then supply year, director, country, language and — the part
that matters here — the projection format, which is how their 35 mm and 16 mm
screenings get tagged.

Théâtre Outremont lives in outremont.py; it is a different site entirely.
"""

from __future__ import annotations

import datetime as dt
import re
import time
import unicodedata

from common import Screening, Venue, clean, http_get, log, parse_time, strip_html, today

BASE = "https://www.cinematheque.qc.ca"
LIST_PAGES = 4          # the programme paginates; this covers ~3 months
MAX_DETAILS = 70

VENUE = Venue(
    id="cinematheque",
    name="Cinémathèque québécoise",
    short_name="Cinémathèque",
    address="335 boulevard De Maisonneuve Est",
    neighbourhood="Quartier Latin",
    lat=45.5150, lng=-73.5610,
    url=f"{BASE}/fr/programme/",
    kind="repertory",
    source="cinematheque",
)

MODAL_RE = re.compile(r'js-struct-modal[^>]*data-id="modal-tickets-(\d+)"')
TITLE_RE = re.compile(r'class="font-weight-medium">([^<]+)</div>')
SHOW_RE = re.compile(
    r'href="(https://omniwebticketing[^"]*?schdate=(\d{4}-\d{2}-\d{2})[^"]*)"[^>]*>.*?à\s*(\d{1,2}:\d{2})',
    re.S,
)
FILM_LINK_RE = re.compile(r'href="(/fr/cinema/([a-z0-9-]+)/)"')


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def _strip_noise(html: str) -> str:
    html = re.sub(r"<svg.*?</svg>", " ", html, flags=re.S)
    return re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)


def _field(text: str, label: str) -> str:
    """Detail pages render label/value pairs on consecutive lines."""
    m = re.search(rf"(?im)^\s*{label}\s*$\n+\s*(.+?)\s*$", text)
    return clean(m.group(1)) if m else ""


def _detail(slug: str) -> dict:
    try:
        html = http_get(f"{BASE}/fr/cinema/{slug}/", browser_ua=True, retries=2, timeout=30)
    except Exception as e:  # noqa: BLE001
        log(f"[cinematheque] detail {slug}: {e}")
        return {}
    text = strip_html(_strip_noise(html))
    out: dict = {}

    year = _field(text, "Année")
    if re.match(r"^\d{4}", year or ""):
        out["year"] = int(year[:4])
    out["director"] = _field(text, "Réalisé par") or _field(text, "Réalisation")
    out["country"] = _field(text, "Pays")
    out["genre"] = _field(text, "Genre")
    out["format"] = _field(text, "Format")
    out["language"] = _field(text, "Langue")

    dur = _field(text, "Durée")
    md = re.search(r"(\d+)", dur or "")
    if md:
        out["runtime"] = int(md.group(1))

    m = re.search(r'<meta property="og:image" content="([^"]+)"', html)
    if m:
        out["poster"] = m.group(1)
    m = re.search(r'<meta property="og:description" content="([^"]+)"', html)
    if m:
        out["synopsis"] = clean(m.group(1))
    return {k: v for k, v in out.items() if v}


def _parse_listing(html: str) -> tuple[list[dict], dict]:
    """-> ([{title, shows:[(url, date, time)]}], {normalized title: slug})"""
    h = _strip_noise(html)

    slugs = {}
    for _, slug in FILM_LINK_RE.findall(h):
        slugs.setdefault(_norm(slug.replace("-", "")), slug)

    marks = [(m.group(1), m.start()) for m in MODAL_RE.finditer(h)]
    films = []
    for i, (_mid, pos) in enumerate(marks):
        end = marks[i + 1][1] if i + 1 < len(marks) else len(h)
        seg = h[pos:end]
        t = TITLE_RE.search(seg)
        shows = SHOW_RE.findall(seg)
        if t and shows:
            films.append({"title": clean(t.group(1)), "shows": shows})
    return films, slugs


def _tags_for(fmt: str, year, title: str) -> tuple:
    tags = ["repertory"]
    f = (fmt or "").lower()
    if "35" in f:
        tags += ["celluloid", "35mm"]
    if "16" in f:
        tags += ["celluloid", "16mm"]
    if "70" in f:
        tags += ["celluloid", "70mm"]
    if "restaur" in f or "restaur" in title.lower():
        tags.append("restoration")
    if isinstance(year, int) and year and year <= today().year - 12:
        tags.append("classic")
    return tuple(dict.fromkeys(tags))


def fetch() -> tuple[list[Venue], list[Screening]]:
    films: list[dict] = []
    slugs: dict[str, str] = {}
    seen_titles: set[str] = set()

    for page in range(1, LIST_PAGES + 1):
        url = f"{BASE}/fr/programme/" + (f"?page={page}" if page > 1 else "")
        try:
            html = http_get(url, browser_ua=True, retries=2, timeout=35)
        except Exception as e:  # noqa: BLE001
            log(f"[cinematheque] listing page {page}: {e}")
            break
        got, page_slugs = _parse_listing(html)
        slugs.update(page_slugs)
        fresh = [f for f in got if _norm(f["title"]) not in seen_titles]
        for f in fresh:
            seen_titles.add(_norm(f["title"]))
        films.extend(fresh)
        log(f"[cinematheque] page {page}: {len(fresh)} films")
        if not fresh:
            break
        time.sleep(0.4)

    if not films:
        raise RuntimeError("no ticket modals found on the programme pages")

    horizon = today() + dt.timedelta(days=150)
    screenings: list[Screening] = []
    details_fetched = 0

    for f in films:
        key = _norm(f["title"])
        slug = slugs.get(key)
        if not slug:                      # fall back to the closest slug
            for k, v in slugs.items():
                if k.startswith(key[:14]) or key.startswith(k[:14]):
                    slug = v
                    break

        info = {}
        if slug and details_fetched < MAX_DETAILS:
            info = _detail(slug)
            details_fetched += 1
            time.sleep(0.35)

        film_url = f"{BASE}/fr/cinema/{slug}/" if slug else VENUE.url
        tags = _tags_for(info.get("format", ""), info.get("year"), f["title"])

        for ticket_url, date_s, time_s in f["shows"]:
            try:
                d = dt.date.fromisoformat(date_s)
            except ValueError:
                continue
            if d < today() or d > horizon:
                continue
            hm = parse_time(time_s)
            if not hm:
                continue
            screenings.append(Screening(
                venue_id=VENUE.id,
                title=f["title"],
                start=f"{date_s}T{hm[0]:02d}:{hm[1]:02d}",
                date=date_s,
                time=f"{hm[0]:02d}:{hm[1]:02d}",
                url=film_url,
                ticket_url=clean(ticket_url).replace("&amp;", "&"),
                version_raw=info.get("language", ""),
                fmt=info.get("format", ""),
                year=info.get("year"),
                runtime=info.get("runtime"),
                genres=tuple(g for g in [info.get("genre", "")] if g),
                synopsis=info.get("synopsis", ""),
                poster=info.get("poster", ""),
                director=info.get("director", ""),
                country=info.get("country", ""),
                source="cinematheque",
                tags=tags,
            ))

    log(f"[cinematheque] {len(screenings)} showtimes from {len(films)} films")
    return [VENUE], screenings
