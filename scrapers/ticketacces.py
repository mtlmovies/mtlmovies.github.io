"""TicketAcces-powered venues: Cinéma Moderne and Cinéma Public.

Both cinemas sell through TicketAcces, which publishes the full programme as
plain server-rendered HTML. That listing is far more reliable to reach than the
cinemas' own sites (which sit behind WAFs), and it carries richer metadata:
synopsis, director, country, year, projection format and the version/subtitles.
"""

from __future__ import annotations

import datetime as dt
import re
import time

from common import (
    Screening,
    Venue,
    clean,
    http_get,
    lang_bundle,
    log,
    merge_i18n,
    month_from_name,
    parse_time,
    strip_html,
    today,
)

ORGS = {
    "moderne": dict(
        host="cinemamoderne.ticketacces.net",
        venues=[
            Venue(
                id="moderne", name="Cinéma Moderne", short_name="Moderne",
                address="5150 boulevard Saint-Laurent", neighbourhood="Mile End",
                lat=45.5231, lng=-73.5977,
                url="https://www.cinemamoderne.com/", kind="repertory", source="ticketacces",
            )
        ],
        match=[("", "moderne")],
    ),
    "public": dict(
        host="cinemapublic.ticketacces.net",
        venues=[
            Venue(
                id="public-casa", name="Cinéma Public — Casa d'Italia", short_name="Public (Casa)",
                address="505 rue Jean-Talon Est", neighbourhood="Petite-Patrie",
                lat=45.5397, lng=-73.6165,
                url="https://cinemapublic.ca/", kind="repertory", source="ticketacces",
            ),
            Venue(
                id="public-livart", name="Cinéma Public — Le Livart", short_name="Public (Livart)",
                address="3980 rue Saint-Denis", neighbourhood="Plateau",
                lat=45.5227, lng=-73.5745,
                url="https://cinemapublic.ca/", kind="repertory", source="ticketacces",
            ),
        ],
        # Resolve which room a showtime belongs to from its printed address.
        match=[("livart", "public-livart"), ("saint-denis", "public-livart"),
               ("st-denis", "public-livart"), ("casa", "public-casa"),
               ("jean-talon", "public-casa"), ("berri", "public-casa")],
    ),
}

EVENT_RE = re.compile(r"representations/index\.cfm\?EvenementID=(\d+)")
ROW_RE = re.compile(r"<tr>(.*?)</tr>", re.S)
CAL_RE = re.compile(
    r'<div class="calendrier[^"]*">\s*'
    r'<span class="titre">([^<]*)</span>\s*'
    r'<span class="contenu"><strong>(\d{1,2})</strong><br\s*/?>\s*([A-Za-zÀ-ÿ.]+)<br\s*/?>\s*'
    r'<span class="calendrier-annee">(\d{4})</span></span>\s*'
    r'<span class="pied">([^<]*)</span>',
    re.S,
)
H3_RE = re.compile(r"<h3>(.*?)</h3>", re.S)
FIELD_RE = re.compile(
    r"<strong>\s*([^<]{2,40}?)\s*</strong>\s*<br\s*/?>\s*<span class=\"light\">(.*?)</span>",
    re.S,
)


def _org_page(host: str) -> str:
    return http_get(f"https://{host}/fr/organisation/index.cfm", browser_ua=True)


def _event_page(host: str, eid: str) -> str:
    return http_get(
        f"https://{host}/fr/organisation/representations/index.cfm?EvenementID={eid}",
        browser_ua=True,
    )


def _event_page_en(host: str, eid: str) -> str:
    """The same event under `/en/`. Not every organisation translates its
    programme, so this is allowed to come back empty."""
    try:
        return http_get(
            f"https://{host}/en/organisation/representations/index.cfm?EvenementID={eid}",
            browser_ua=True, retries=1,
        )
    except Exception:  # noqa: BLE001
        return ""


def _english_i18n(html: str) -> dict:
    if not html:
        return {}
    title_m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
    return lang_bundle(
        "en",
        title=clean(title_m.group(1)) if title_m else "",
        synopsis=_synopsis(html),
    )


def _fields(html: str) -> dict:
    out = {}
    for label, value in FIELD_RE.findall(html):
        out[clean(label).lower()] = clean(value)
    return out


def _runtime(s: str):
    s = (s or "").lower()
    m = re.search(r"(\d+)\s*h\s*(\d+)?", s)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2) or 0)
    m = re.search(r"(\d+)\s*min", s)
    return int(m.group(1)) if m else None


def _from_body(text: str, label: str) -> str:
    m = re.search(rf"{label}\s*:\s*(.+)", text)
    return clean(m.group(1)).split("\n")[0] if m else ""


def _synopsis(html: str) -> str:
    """The description sits after the metadata strip and before the showtimes."""
    end = html.find('id="resultats"')
    if end < 0:
        end = len(html)
    # Start right after the last "<strong>Label</strong><span class=light>" field.
    start = 0
    for m in FIELD_RE.finditer(html[:end]):
        start = m.end()
    chunk = html[start:end]
    txt = strip_html(chunk)
    # Everything before the credits block is the synopsis.
    cut = re.search(
        r"(?im)^\s*(réalisation|realisation|directed by|director|pays|country|"
        r"année|annee|year|format)\s*:", txt)
    if cut:
        txt = txt[: cut.start()]
    # Drop boilerplate + the credits lines we extract separately.
    lines = []
    for line in txt.split("\n"):
        l = line.strip()
        if not l or len(l) < 3:
            continue
        low = l.lower()
        if low.startswith(("réalisation", "realisation", "director", "directed by",
                           "pays", "country", "année", "annee", "year", "format",
                           "bande annonce", "trailer", "genre", "durée", "duree",
                           "running time", "distribution", "cast")):
            continue
        if "cookie" in low or "navigateur" in low or "voir les dates" in low:
            continue
        lines.append(l)
    return "\n\n".join(lines[:6]).strip()


def _parse_event(html: str, org_key: str, cfg: dict, eid: str,
                 en_html: str = "") -> list[Screening]:
    fields = _fields(html)
    text = strip_html(html)

    title_m = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.S)
    base_title = clean(title_m.group(1)) if title_m else ""

    director = _from_body(text, "Réalisation") or _from_body(text, "Réalisateur")
    country = _from_body(text, "Pays")
    year_s = _from_body(text, "Année")
    year = int(year_s[:4]) if re.match(r"^\d{4}", year_s or "") else None
    fmt_body = _from_body(text, "Format")

    genre = fields.get("genre", "")
    genres = tuple(
        g for g in (clean(x) for x in re.split(r"[•·,/]", genre)) if g and g.lower() != "cinéma"
    )
    runtime = _runtime(fields.get("durée") or fields.get("duree") or "")
    extra = fields.get("informations supplémentaires", "")
    synopsis = _synopsis(html)
    i18n = merge_i18n(
        lang_bundle("fr", synopsis=synopsis, genres=genres, country=country),
        _english_i18n(en_html),
    )

    trailer_m = re.search(r'href="(https://(?:www\.)?(?:youtube\.com|youtu\.be|vimeo\.com)[^"]*)"', html)
    trailer = trailer_m.group(1) if trailer_m else ""
    poster_m = re.search(r'<img[^>]+src="([^"]+(?:evenement|affiche|upload)[^"]*)"', html, re.I)
    poster = poster_m.group(1) if poster_m else ""
    if poster.startswith("/"):
        poster = f"https://{cfg['host']}{poster}"

    event_url = f"https://{cfg['host']}/fr/organisation/representations/index.cfm?EvenementID={eid}"

    out: list[Screening] = []
    horizon = today() + dt.timedelta(days=120)

    for row in ROW_RE.findall(html):
        cal = CAL_RE.search(row)
        if not cal:
            continue
        _dow, day_s, mon_s, year_s2, time_s = cal.groups()
        mon = month_from_name(mon_s)
        hm = parse_time(time_s)
        if not mon or not hm:
            continue
        try:
            d = dt.date(int(year_s2), mon, int(day_s))
        except ValueError:
            continue
        if d < today() or d > horizon:
            continue

        h3 = H3_RE.search(row)
        row_title = base_title
        version_raw = extra
        if h3:
            raw = strip_html(h3.group(1))
            parts = [p.strip() for p in raw.split("\n") if p.strip()]
            if parts:
                row_title = parts[0].strip(" -")
            for p in parts[1:]:
                p = p.strip(" -")
                if p:
                    version_raw = p
        row_title = re.sub(r"\s*-\s*$", "", row_title).strip() or base_title

        # Which room?
        row_text = strip_html(row).lower()
        venue_id = cfg["venues"][0].id
        for needle, vid in cfg["match"]:
            if needle and needle in row_text:
                venue_id = vid
                break

        fmt = ""
        for token in ("35mm", "70mm", "4k", "dcp", "imax", "3d"):
            if token in (version_raw or "").lower() or token in (fmt_body or "").lower():
                fmt = token.upper()
                break

        tags = []
        low_t = f"{row_title} {fmt_body} {version_raw}".lower()
        if any(w in low_t for w in ("restaur", "anniversaire", "anniversary", "4k")):
            tags.append("restoration")
        if year and year < today().year - 12:
            tags.append("classic")
        if fmt in {"35MM", "70MM"}:
            tags.append("celluloid")

        out.append(
            Screening(
                venue_id=venue_id,
                title=row_title,
                start=f"{d.isoformat()}T{hm[0]:02d}:{hm[1]:02d}",
                date=d.isoformat(),
                time=f"{hm[0]:02d}:{hm[1]:02d}",
                url=event_url,
                ticket_url=event_url,
                version_raw=version_raw,
                fmt=fmt,
                year=year,
                runtime=runtime,
                genres=genres,
                synopsis=synopsis,
                poster=poster,
                director=director,
                country=country,
                trailer=trailer,
                source=f"ticketacces:{org_key}",
                tags=tuple(dict.fromkeys(tags)),
                i18n=merge_i18n(lang_bundle("fr", title=row_title), i18n),
            )
        )
    return out


def fetch_org(org_key: str) -> tuple[list[Venue], list[Screening]]:
    cfg = ORGS[org_key]
    html = _org_page(cfg["host"])
    eids = list(dict.fromkeys(EVENT_RE.findall(html)))
    log(f"[ticketacces:{org_key}] {len(eids)} events")

    screenings: list[Screening] = []
    for eid in eids:
        try:
            page = _event_page(cfg["host"], eid)
            en_page = _event_page_en(cfg["host"], eid)
            screenings.extend(_parse_event(page, org_key, cfg, eid, en_page))
        except Exception as e:  # noqa: BLE001
            log(f"[ticketacces:{org_key}] event {eid}: {e}")
        time.sleep(0.2)

    return cfg["venues"], screenings


# Cinéma Moderne has its own richer adapter (cinemamoderne.py) which falls back
# to fetch_org("moderne") here; only Cinéma Public is scraped from this module
# directly, so the two never produce duplicate screenings.
DIRECT_ORGS = ["public"]


def fetch() -> tuple[list[Venue], list[Screening]]:
    venues: list[Venue] = []
    screenings: list[Screening] = []
    errors = []
    for key in DIRECT_ORGS:
        try:
            v, s = fetch_org(key)
            venues.extend(v)
            screenings.extend(s)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{key}: {e}")
            log(f"[ticketacces] {key} FAILED: {e}")
    if errors and not screenings:
        raise RuntimeError("; ".join(errors))
    return venues, screenings
