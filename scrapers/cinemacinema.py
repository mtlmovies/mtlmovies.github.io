"""Cinéma Cinéma group: Cinéma du Parc, Cinéma du Musée, Cinéma Beaubien.

All three run one SvelteKit app (cinemacinema.ca). SvelteKit exposes every
route's loader payload at `<route>/__data.json` in devalue's flattened format,
so we read structured data instead of parsing markup.
"""

from __future__ import annotations

import datetime as dt

from common import (
    Screening,
    Venue,
    clean,
    log,
    http_json,
    parse_time,
    strip_html,
    today,
)

BASE = "https://cinemacinema.ca"

# cinema_id -> venue
CINEMAS = {
    1: Venue(
        id="beaubien",
        name="Cinéma Beaubien",
        short_name="Beaubien",
        address="2396 rue Beaubien Est",
        neighbourhood="Rosemont",
        lat=45.5468, lng=-73.5860,
        url=f"{BASE}/fr/cinema-beaubien",
        kind="repertory",
        source="cinemacinema",
    ),
    2: Venue(
        id="parc",
        name="Cinéma du Parc",
        short_name="du Parc",
        address="3575 avenue du Parc",
        neighbourhood="Milton-Parc",
        lat=45.5100, lng=-73.5745,
        url=f"{BASE}/fr/cinema-du-parc",
        kind="repertory",
        source="cinemacinema",
    ),
    3: Venue(
        id="musee",
        name="Cinéma du Musée",
        short_name="du Musée",
        address="1379 rue Sherbrooke Ouest",
        neighbourhood="Golden Square Mile",
        lat=45.4986, lng=-73.5793,
        url=f"{BASE}/fr/cinema-du-musee",
        kind="museum",
        source="cinemacinema",
    ),
}

SLUG_BY_ID = {1: "cinema-beaubien", 2: "cinema-du-parc", 3: "cinema-du-musee"}


# ---------------------------------------------------------------------------
# devalue decoding
# ---------------------------------------------------------------------------

def unflatten(arr):
    """Rehydrate SvelteKit's flattened devalue array (index references)."""
    memo: dict[int, object] = {}
    HOLES = {-1: None, -2: None, -3: float("nan"), -4: float("inf"), -5: float("-inf"), -6: 0.0}

    def hyd(i):
        if isinstance(i, str):
            return i
        if not isinstance(i, int):
            return i
        if i in HOLES:
            return HOLES[i]
        if i in memo:
            return memo[i]
        v = arr[i]
        if isinstance(v, list):
            out: list = []
            memo[i] = out
            out.extend(hyd(x) for x in v)
            return out
        if isinstance(v, dict):
            out_d: dict = {}
            memo[i] = out_d
            for k, x in v.items():
                out_d[k] = hyd(x)
            return out_d
        memo[i] = v
        return v

    return hyd(0)


def fetch_data(path: str) -> list:
    """Fetch `<path>/__data.json` and return the rehydrated loader nodes."""
    url = f"{BASE}{path.rstrip('/')}/__data.json"
    raw = http_json(url)
    nodes = []
    for node in raw.get("nodes", []):
        if node and node.get("type") == "data":
            nodes.append(unflatten(node["data"]))
        else:
            nodes.append(None)
    return nodes


def find_key(nodes, key):
    for n in nodes:
        if isinstance(n, dict) and key in n:
            return n[key]
    return None


# ---------------------------------------------------------------------------

def _genres(f: dict) -> tuple:
    return tuple(
        g for g in (clean(f.get(f"genre{i}")) for i in (1, 2, 3)) if g
    )


def _countries(f: dict) -> str:
    return ", ".join(
        c for c in (clean(f.get(f"origine{i}")) for i in (1, 2, 3)) if c
    )


def _tags(film: dict, rep: dict) -> tuple:
    tags = []
    title = (film.get("titre") or "").lower()
    year = film.get("annee")
    if film.get("prog_special"):
        tags.append("special")
    if any(w in title for w in ("anniversaire", "anniversary", "restaur")):
        tags.append("restoration")
    if isinstance(year, int) and year and year < today().year - 12:
        tags.append("classic")
    if clean(rep.get("format")).upper() in {"35MM", "70MM", "16MM"}:
        tags.append("celluloid")
    return tuple(dict.fromkeys(tags))


def fetch() -> tuple[list[Venue], list[Screening]]:
    # One page load carries the site-wide film catalogue in its layout data.
    nodes = fetch_data("/fr/cinema-du-parc/horaire")
    playing = find_key(nodes, "cmFilmsPlaying") or []
    upcoming = find_key(nodes, "cmFilmsUpcoming") or []

    seen_slugs: dict[str, dict] = {}
    for f in list(playing) + list(upcoming):
        slug = clean(f.get("slug"))
        if slug:
            seen_slugs.setdefault(slug, f)

    log(f"[cinemacinema] {len(seen_slugs)} film pages to read")

    horizon = today() + dt.timedelta(days=90)
    screenings: list[Screening] = []

    for slug, stub in seen_slugs.items():
        try:
            fnodes = fetch_data(f"/fr/films/{slug}")
        except Exception as e:  # noqa: BLE001
            log(f"[cinemacinema] skip {slug}: {e}")
            continue

        film = find_key(fnodes, "cmFilmCurrent") or stub
        reps = find_key(fnodes, "cmRepresentationsCurrent") or []
        if not reps:
            continue

        film_url = f"{BASE}/fr/films/{slug}"
        synopsis = strip_html(film.get("synopsis"))
        year = film.get("annee") if isinstance(film.get("annee"), int) else None
        runtime = film.get("duree") if isinstance(film.get("duree"), int) else None

        for rep in reps:
            venue = CINEMAS.get(rep.get("cinema_id"))
            if not venue:
                continue
            date_s = (rep.get("representation_date") or "")[:10]
            hm = parse_time(rep.get("heure_debut"))
            if not date_s or not hm:
                continue
            try:
                d = dt.date.fromisoformat(date_s)
            except ValueError:
                continue
            if d < today() or d > horizon:
                continue

            screenings.append(
                Screening(
                    venue_id=venue.id,
                    title=clean(film.get("titre")) or clean(stub.get("titre")),
                    original_title=clean(film.get("original_title")),
                    start=f"{date_s}T{hm[0]:02d}:{hm[1]:02d}",
                    date=date_s,
                    time=f"{hm[0]:02d}:{hm[1]:02d}",
                    url=film_url,
                    ticket_url=film_url if rep.get("url_bel") else "",
                    version_raw=clean(rep.get("version") or film.get("version")),
                    fmt=clean(rep.get("format")),
                    room=str(rep.get("salle") or ""),
                    year=year,
                    runtime=runtime,
                    genres=_genres(film),
                    synopsis=synopsis,
                    poster=clean(film.get("poster_url")),
                    backdrop=clean(film.get("image1_url")),
                    director=clean(film.get("realisateur")),
                    cast=clean(film.get("acteurs")),
                    trailer=clean(film.get("bande_annonce_url")),
                    country=_countries(film),
                    rating=clean(film.get("classment")),
                    source="cinemacinema",
                    tags=_tags(film, rep),
                )
            )

    return list(CINEMAS.values()), screenings
