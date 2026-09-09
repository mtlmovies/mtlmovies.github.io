"""Théâtre Outremont.

A performing-arts venue that also programmes cinema (Ciné-Outremont,
Ciné-Rencontre, Ciné-Récré). Its programme grid gives each event a category,
a title and a date — but no start time.

The start times exist only inside its Tuxedo box office, and there is no
public way to read them. Traced in full: the ticket page is an Angular app
whose only data request is its own configuration.json; every same-origin API
route returns the app shell; the app is backed by a Firebase Realtime
Database that answers "Permission denied" on every path even with a valid
anonymous session; the project has Firestore disabled; and neither Tuxedo
property publishes a sitemap or feed. Rendered in a real browser the page
never gets past "Chargement en cours".

So this tries, in order:
  1. /cinema/, their dedicated cinema page, for a date *and* a time;
  2. /programmation/, filtered to the cinema categories, which yields a time
     only when one happens to be printed on the card.

A screening with no start time is not a showtime, so anything without one is
dropped and reported rather than guessed at.
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

BASE = "https://theatreoutremont.ca"

VENUE = Venue(
    id="outremont",
    name="Théâtre Outremont",
    short_name="Outremont",
    address="1248 avenue Bernard",
    neighbourhood="Outremont",
    lat=45.5197, lng=-73.6096,
    url=f"{BASE}/programmation/",
    kind="repertory",
    source="outremont",
)

CARD_RE = re.compile(r'<a href="([^"]+)"[^>]*class="spectacle-link">(.*?)</a>', re.S)
CAT_RE = re.compile(r"spectacle-category'>([^<]*)<")
ARTIST_RE = re.compile(r"spectacle-artiste'>([^<]*)<")
SUBTITLE_RE = re.compile(r"spectacle-title'>([^<]*)<")
DATES_RE = re.compile(r"spectacle-dates'>([^<]*)<")

# "lundi 21 septembre 2026" optionally followed by a time
FR_DATE_RE = re.compile(
    r"(?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)?\s*"
    r"(\d{1,2})\s+([a-zéûôA-ZÉÛÔ]{3,10})\.?\s+(\d{4})"
    r"(?:[^0-9]{0,24}?(\d{1,2}\s*[h:]\s*\d{0,2}))?",
    re.I,
)

CINEMA_CATS = ("cinéma", "cinema", "ciné", "cine")


def _is_cinema(cat: str) -> bool:
    c = (cat or "").lower()
    return any(k in c for k in CINEMA_CATS)


def _parse_cards(html: str) -> list[dict]:
    out = []
    for url, seg in CARD_RE.findall(html):
        cat = clean((CAT_RE.search(seg) or [None, ""]) and (CAT_RE.search(seg).group(1) if CAT_RE.search(seg) else ""))
        if not _is_cinema(cat):
            continue
        title = clean(ARTIST_RE.search(seg).group(1)) if ARTIST_RE.search(seg) else ""
        sub = clean(SUBTITLE_RE.search(seg).group(1)) if SUBTITLE_RE.search(seg) else ""
        dates = clean(DATES_RE.search(seg).group(1)) if DATES_RE.search(seg) else ""
        if not title and sub:
            title, sub = sub, ""
        if title and dates:
            out.append({"title": title, "subtitle": sub, "dates": dates,
                        "url": clean(url), "category": cat})
    return out


def _screenings_from(text: str, title: str, url: str, category: str) -> list[Screening]:
    """Pull date+time pairs out of a blob of French text."""
    horizon = today() + dt.timedelta(days=180)
    out, seen = [], set()

    for m in FR_DATE_RE.finditer(text):
        day, mon_name, year, time_raw = m.groups()
        mon = month_from_name(mon_name)
        if not mon or not time_raw:
            continue                      # a date with no time is not a showtime
        hm = parse_time(time_raw.replace(" ", "").rstrip("h") + ("00" if time_raw.rstrip().endswith("h") else ""))
        if not hm:
            hm = parse_time(time_raw)
        if not hm:
            continue
        try:
            d = dt.date(int(year), mon, int(day))
        except ValueError:
            continue
        if d < today() or d > horizon:
            continue
        key = (d.isoformat(), f"{hm[0]:02d}:{hm[1]:02d}")
        if key in seen:
            continue
        seen.add(key)

        tags = ["repertory"]
        if "rencontre" in (category or "").lower():
            tags.append("qa")
        out.append(Screening(
            venue_id=VENUE.id,
            title=title,
            start=f"{d.isoformat()}T{hm[0]:02d}:{hm[1]:02d}",
            date=d.isoformat(),
            time=f"{hm[0]:02d}:{hm[1]:02d}",
            url=url or VENUE.url,
            ticket_url=url or "",
            source="outremont",
            tags=tuple(tags),
        ))
    return out


def fetch() -> tuple[list[Venue], list[Screening]]:
    screenings: list[Screening] = []
    dated_but_timeless = 0
    problems = []

    # 1. The dedicated cinema page, if it is reachable.
    try:
        html = http_get(f"{BASE}/cinema/", browser_ua=True, retries=2, timeout=40)
        text = strip_html(re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html))
        got = _screenings_from(text, "", f"{BASE}/cinema/", "")
        # Only usable if we can also attribute a title to each; the page layout
        # is unverified, so treat a bare date+time sweep as untrustworthy.
        log(f"[outremont] /cinema/ reachable, {len(got)} date+time pairs found")
    except Exception as e:  # noqa: BLE001
        problems.append(f"/cinema/: {e}")
        log(f"[outremont] /cinema/: {e}")

    # 2. The programme grid, filtered to cinema categories.
    try:
        html = http_get(f"{BASE}/programmation/", browser_ua=True, retries=2, timeout=40)
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"programme unreachable: {e}") from e

    cards = _parse_cards(html)
    log(f"[outremont] {len(cards)} cinema events on the programme")

    for c in cards:
        title = c["title"] if not c["subtitle"] else f"{c['title']} — {c['subtitle']}"
        got = _screenings_from(c["dates"], title, c["url"], c["category"])
        if got:
            screenings.extend(got)
        else:
            dated_but_timeless += 1

    if not screenings:
        raise RuntimeError(
            f"{len(cards)} cinema events listed, none with a start time. "
            f"Their programme publishes dates only, and the start times are "
            f"held in a Tuxedo box office with no publicly readable source "
            f"(Firebase RTDB denies every path even to an anonymous session; "
            f"Firestore is disabled; no sitemap or feed)."
            + (f" {'; '.join(problems)}" if problems else "")
        )

    log(f"[outremont] {len(screenings)} showtimes "
        f"({dated_but_timeless} events had a date but no time)")
    return [VENUE], screenings
