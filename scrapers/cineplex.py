"""Cineplex circuit (Scotiabank, Forum, Quartier Latin, Starcité, Laval, ...).

Uses the same public JSON API the cineplex.com front-end calls. The
subscription key below is the one shipped in their public web bundle.
"""

from __future__ import annotations

import datetime as dt
import time
import urllib.parse

from common import (Screening, Venue, clean, http_json, lang_bundle, log,
                    merge_i18n, parse_time, today)

API = "https://apis.cineplex.com/prod/cpx/theatrical/api"
KEY = "dcdac5601d864addbc2675a2e96cb1f8"
HEADERS = {
    "Ocp-Apim-Subscription-Key": KEY,
    "Origin": "https://www.cineplex.com",
    "Referer": "https://www.cineplex.com/",
}

DAYS_AHEAD = 10
# The API answers in whichever language is asked for. English is the primary
# read; French is collected over the first few days only, which is enough to
# see every film in the circuit without doubling the day-by-day crawl.
FRENCH_DAYS = 4

# Greater Montréal locations only (theatreId -> descriptor).
THEATRES = {
    9406: dict(id="scotiabank", name="Cinéma Banque Scotia Montréal", short="Scotiabank",
               address="977 rue Sainte-Catherine Ouest", neighbourhood="Centre-ville",
               lat=45.5017, lng=-73.5731, city="Montréal"),
    9109: dict(id="forum", name="Cineplex Forum et VIP", short="Forum",
               address="2313 rue Sainte-Catherine Ouest", neighbourhood="Shaughnessy Village",
               lat=45.4894, lng=-73.5820, city="Montréal"),
    9172: dict(id="quartier-latin", name="Cineplex Odeon Quartier Latin", short="Quartier Latin",
               address="350 rue Émery", neighbourhood="Quartier Latin",
               lat=45.5136, lng=-73.5629, city="Montréal"),
    9401: dict(id="starcite", name="Cinéma Starcité Montréal", short="Starcité",
               address="4825 avenue Pierre-De Coubertin", neighbourhood="Hochelaga",
               lat=45.5596, lng=-73.5480, city="Montréal"),
    9195: dict(id="angrignon", name="Famous Players Carrefour Angrignon", short="Angrignon",
               address="7077 boulevard Newman", neighbourhood="LaSalle",
               lat=45.4479, lng=-73.6039, city="Montréal"),
    9121: dict(id="royalmount", name="Cineplex Royalmount", short="Royalmount",
               address="6900 boulevard Décarie", neighbourhood="Mont-Royal",
               lat=45.5165, lng=-73.6672, city="Mont-Royal"),
    9407: dict(id="kirkland", name="Cineplex Kirkland", short="Kirkland",
               address="3200 rue Jean-Yves", neighbourhood="West Island",
               lat=45.4506, lng=-73.8666, city="Kirkland"),
    9408: dict(id="cineplex-laval", name="Cineplex Laval", short="Laval",
               address="2900 boulevard le Carrefour", neighbourhood="Laval",
               lat=45.5700, lng=-73.7523, city="Laval"),
    9185: dict(id="brossard", name="Cineplex Odeon Brossard et VIP", short="Brossard",
               address="9350 boulevard Leduc", neighbourhood="Rive-Sud",
               lat=45.4508, lng=-73.4419, city="Brossard"),
    9143: dict(id="saint-bruno", name="Cineplex Odeon Saint-Bruno", short="Saint-Bruno",
               address="100 boulevard des Promenades", neighbourhood="Rive-Sud",
               lat=45.5342, lng=-73.3499, city="Saint-Bruno"),
    9153: dict(id="dorion", name="Cineplex Odeon Carrefour Dorion", short="Vaudreuil",
               address="440 boulevard Harwood", neighbourhood="Vaudreuil",
               lat=45.3959, lng=-74.0246, city="Vaudreuil-Dorion"),
}

PREMIUM = {"IMAX", "ULTRAAVX", "VIP", "4DX", "SCREENX", "D-BOX", "DBOX"}


def _venues() -> list[Venue]:
    out = []
    for t in THEATRES.values():
        out.append(
            Venue(
                id=t["id"], name=t["name"], short_name=t["short"], address=t["address"],
                city=t["city"], neighbourhood=t["neighbourhood"], lat=t["lat"], lng=t["lng"],
                url=f"https://www.cineplex.com/theatre/{t['id']}",
                chain="cineplex", kind="multiplex", source="cineplex",
            )
        )
    return out


def _get(path: str, **params):
    url = f"{API}{path}?" + urllib.parse.urlencode(params)
    return http_json(url, headers=HEADERS)


def _experience_tags(exp: dict) -> tuple[str, tuple]:
    types = [clean(t) for t in (exp.get("experienceTypes") or [])]
    fmt = ""
    tags = []
    for t in types:
        up = t.upper().replace(" ", "")
        if up in PREMIUM:
            tags.append("premium-format")
        if up in {"IMAX", "ULTRAAVX", "SCREENX", "4DX", "VIP", "3D"}:
            fmt = fmt or t
    return (fmt or "2D"), tuple(dict.fromkeys(tags))


def _film_key(movie: dict) -> str:
    """Identify a film across the two language responses."""
    for k in ("id", "filmId", "vistaFilmId", "filmUrl", "name"):
        v = movie.get(k)
        if v:
            return str(v).strip().lower()
    return ""


def _movies(data) -> list:
    for theatre in data or []:
        for dateblock in theatre.get("dates") or []:
            for movie in dateblock.get("movies") or []:
                yield movie


def _french_catalogue(start: dt.date) -> dict:
    """film key -> French title and genres, read from the same public API."""
    out: dict[str, dict] = {}
    for tid in THEATRES:
        for offset in range(FRENCH_DAYS):
            day = start + dt.timedelta(days=offset)
            try:
                data = _get("/v1/showtimes", language="fr", locationId=tid,
                            date=day.isoformat())
            except Exception as e:  # noqa: BLE001
                log(f"[cineplex] fr {tid} {day}: {e}")
                continue
            for movie in _movies(data):
                key = _film_key(movie)
                title = clean(movie.get("name"))
                if not key or not title or key in out:
                    continue
                out[key] = {
                    "title": title,
                    "genres": tuple(clean(g) for g in (movie.get("genres") or []) if g),
                }
            time.sleep(0.15)
    log(f"[cineplex] French titles for {len(out)} films")
    return out


def fetch() -> tuple[list[Venue], list[Screening]]:
    start = today()
    screenings: list[Screening] = []
    french = _french_catalogue(start)

    for tid, meta in THEATRES.items():
        got = 0
        for offset in range(DAYS_AHEAD):
            day = start + dt.timedelta(days=offset)
            try:
                data = _get("/v1/showtimes", language="en", locationId=tid, date=day.isoformat())
            except Exception as e:  # noqa: BLE001
                log(f"[cineplex] {meta['short']} {day}: {e}")
                continue

            for theatre in data or []:
                for dateblock in theatre.get("dates") or []:
                    for movie in dateblock.get("movies") or []:
                        title = clean(movie.get("name"))
                        if not title:
                            continue
                        film_url = ""
                        if movie.get("filmUrl"):
                            film_url = f"https://www.cineplex.com/movie/{movie['filmUrl']}"
                        genres = tuple(clean(g) for g in (movie.get("genres") or []) if g)
                        runtime = movie.get("runtimeInMinutes") or None
                        poster = clean(movie.get("largePosterImageUrl") or movie.get("mediumPosterImageUrl"))
                        fr = french.get(_film_key(movie)) or {}
                        i18n = merge_i18n(
                            lang_bundle("en", title=title, genres=genres),
                            lang_bundle("fr", title=fr.get("title", ""),
                                        genres=fr.get("genres", ())),
                        )

                        for exp in movie.get("experiences") or []:
                            fmt, extra_tags = _experience_tags(exp)
                            for sess in exp.get("sessions") or []:
                                raw_dt = clean(sess.get("showStartDateTime") or sess.get("showtimeDateTime"))
                                d_s, t_s = "", ""
                                if "T" in raw_dt:
                                    d_s, _, rest = raw_dt.partition("T")
                                    t_s = rest[:5]
                                if not d_s:
                                    d_s = day.isoformat()
                                    hm = parse_time(clean(sess.get("showTime")))
                                    if not hm:
                                        continue
                                    t_s = f"{hm[0]:02d}:{hm[1]:02d}"
                                if not t_s:
                                    continue

                                tags = list(extra_tags)
                                if movie.get("isEvent"):
                                    tags.append("event")

                                screenings.append(
                                    Screening(
                                        venue_id=meta["id"],
                                        title=title,
                                        start=f"{d_s}T{t_s}",
                                        date=d_s,
                                        time=t_s,
                                        url=film_url,
                                        ticket_url=clean(sess.get("ticketingUrl")),
                                        version_raw="VF" if clean(sess.get("language")).lower().startswith("f") else "",
                                        fmt=fmt,
                                        runtime=runtime,
                                        genres=genres,
                                        poster=poster,
                                        source="cineplex",
                                        tags=tuple(dict.fromkeys(tags)),
                                        i18n=i18n,
                                    )
                                )
                                got += 1
            time.sleep(0.15)
        log(f"[cineplex] {meta['short']}: {got} showtimes")

    return _venues(), screenings
