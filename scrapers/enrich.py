"""Film metadata + ratings enrichment.

Priority order for ratings, per request: Letterboxd first, then Rotten Tomatoes
/ IMDb / Metacritic, then TMDB.

Everything is keyless by default:

    title (+year) --> Wikidata --> imdb_id / tmdb_id --> Letterboxd rating

Two optional API keys upgrade the results if present in the environment:
  TMDB_API_KEY  -> better title matching, backdrops, overviews, TMDB score
  OMDB_API_KEY  -> IMDb rating + Rotten Tomatoes + Metacritic

Results are cached in data/enrich_cache.json (committed) so a daily run only
looks up films it has never seen.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.parse

from common import clean, http_get, http_json, log, title_key

TMDB_KEY = os.environ.get("TMDB_API_KEY", "").strip()
OMDB_KEY = os.environ.get("OMDB_API_KEY", "").strip()

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
LETTERBOXD = "https://letterboxd.com"

# Cache entries older than this are refreshed (ratings drift).
CACHE_TTL_DAYS = 21
# A lookup that resolved nothing is retried much sooner: the title may have been
# decorated ("- Staff Picks"), or the film may be too new to be indexed yet.
UNRESOLVED_TTL_DAYS = 3


# ---------------------------------------------------------------------------
# Wikidata (keyless id resolution)
# ---------------------------------------------------------------------------

def _wikidata_ids(title: str, year: int | None, director: str = "") -> dict:
    """Resolve a film title to {imdb_id, tmdb_id, year, wikidata_id}."""
    best: dict = {}
    for lang in ("en", "fr"):
        try:
            res = http_json(
                WIKIDATA_API + "?" + urllib.parse.urlencode({
                    "action": "wbsearchentities", "search": title, "language": lang,
                    "uselang": lang, "type": "item", "limit": 8, "format": "json",
                })
            )
        except Exception:
            continue

        qids = [h["id"] for h in res.get("search", [])]
        if not qids:
            continue

        try:
            ents = http_json(
                WIKIDATA_API + "?" + urllib.parse.urlencode({
                    "action": "wbgetentities", "ids": "|".join(qids[:8]),
                    "props": "claims|labels", "format": "json",
                })
            ).get("entities", {})
        except Exception:
            continue

        for qid in qids:
            ent = ents.get(qid) or {}
            claims = ent.get("claims") or {}

            # instance of (P31) must be film-ish
            inst = {
                c.get("mainsnak", {}).get("datavalue", {}).get("value", {}).get("id")
                for c in claims.get("P31", [])
            }
            FILMISH = {"Q11424", "Q24869", "Q506240", "Q202866", "Q93204", "Q29168811"}
            if not (inst & FILMISH):
                continue

            def first(pid):
                for c in claims.get(pid, []):
                    v = c.get("mainsnak", {}).get("datavalue", {}).get("value")
                    if v is not None:
                        return v
                return None

            pub = first("P577")
            wyear = None
            if isinstance(pub, dict) and pub.get("time"):
                m = re.search(r"(\d{4})", pub["time"])
                wyear = int(m.group(1)) if m else None

            if year and wyear and abs(wyear - year) > 1:
                continue

            cand = {
                "imdb_id": first("P345") or "",
                "tmdb_id": str(first("P4947") or ""),
                "year": wyear,
                "wikidata_id": qid,
            }
            if not cand["imdb_id"] and not cand["tmdb_id"]:
                continue
            # A year match is a strong signal; take it immediately.
            if year and wyear == year:
                return cand
            best = best or cand
        if best and not year:
            return best
    return best


# ---------------------------------------------------------------------------
# TMDB (optional)
# ---------------------------------------------------------------------------

def _tmdb(title: str, year: int | None) -> dict:
    if not TMDB_KEY:
        return {}
    try:
        params = {"api_key": TMDB_KEY, "query": title, "include_adult": "false"}
        if year:
            params["year"] = str(year)
        res = http_json("https://api.themoviedb.org/3/search/movie?" + urllib.parse.urlencode(params))
        hits = res.get("results") or []
        if not hits:
            return {}
        hit = hits[0]
        tmdb_id = hit.get("id")
        out = {
            "tmdb_id": str(tmdb_id or ""),
            "overview": clean(hit.get("overview")),
            "tmdb_rating": hit.get("vote_average") or None,
            "tmdb_votes": hit.get("vote_count") or None,
            "poster": f"https://image.tmdb.org/t/p/w500{hit['poster_path']}" if hit.get("poster_path") else "",
            "backdrop": f"https://image.tmdb.org/t/p/w1280{hit['backdrop_path']}" if hit.get("backdrop_path") else "",
            "original_title": clean(hit.get("original_title")),
        }
        if hit.get("release_date"):
            out["year"] = int(hit["release_date"][:4])
        det = http_json(
            f"https://api.themoviedb.org/3/movie/{tmdb_id}?"
            + urllib.parse.urlencode({"api_key": TMDB_KEY, "append_to_response": "credits"})
        )
        out["imdb_id"] = det.get("imdb_id") or ""
        out["runtime"] = det.get("runtime") or None
        out["genres"] = [g["name"] for g in det.get("genres") or []]
        crew = (det.get("credits") or {}).get("crew") or []
        directors = [c["name"] for c in crew if c.get("job") == "Director"]
        out["director"] = ", ".join(directors)
        castl = (det.get("credits") or {}).get("cast") or []
        out["cast"] = ", ".join(c["name"] for c in castl[:5])
        return {k: v for k, v in out.items() if v}
    except Exception as e:  # noqa: BLE001
        log(f"[enrich] tmdb '{title}': {e}")
        return {}


# ---------------------------------------------------------------------------
# Letterboxd (keyless, highest priority rating)
# ---------------------------------------------------------------------------

_LB_RATING_RE = re.compile(r'"aggregateRating"\s*:\s*\{(.*?)\}', re.S)
_LB_VALUE_RE = re.compile(r'"ratingValue"\s*:\s*([0-9.]+)')
_LB_COUNT_RE = re.compile(r'"ratingCount"\s*:\s*(\d+)')
_LB_REVIEWS_RE = re.compile(r'"reviewCount"\s*:\s*(\d+)')


def _letterboxd(imdb_id: str = "", tmdb_id: str = "") -> dict:
    """Letterboxd exposes /imdb/<id>/ and /tmdb/<id>/ redirects to the film page."""
    for path in (f"/imdb/{imdb_id}/" if imdb_id else "", f"/tmdb/{tmdb_id}/" if tmdb_id else ""):
        if not path:
            continue
        try:
            html = http_get(LETTERBOXD + path, browser_ua=True, retries=2, timeout=30)
        except Exception:
            continue

        out: dict = {}
        # Letterboxd's og:image is a 16:9 still — the only artwork available for
        # venues (Cinéma Moderne, Cinémathèque) that publish none themselves.
        ogi = re.search(r'<meta property="og:image" content="([^"]+)"', html)
        if ogi and "ltrbxd.com" in ogi.group(1) and "empty-poster" not in ogi.group(1):
            out["backdrop"] = ogi.group(1)
        m = re.search(r'<meta property="og:url" content="([^"]+)"', html)
        if m:
            out["letterboxd_url"] = m.group(1)
        else:
            s = re.search(r'data-film-slug="([^"]+)"', html)
            if s:
                out["letterboxd_url"] = f"{LETTERBOXD}/film/{s.group(1)}/"

        block = _LB_RATING_RE.search(html)
        scope = block.group(1) if block else html
        v = _LB_VALUE_RE.search(scope)
        if not v:
            tw = re.search(r'name="twitter:data2" content="([0-9.]+) out of 5"', html)
            if tw:
                out["letterboxd_rating"] = float(tw.group(1))
        else:
            out["letterboxd_rating"] = float(v.group(1))

        c = _LB_COUNT_RE.search(scope) or _LB_REVIEWS_RE.search(scope)
        if c:
            out["letterboxd_votes"] = int(c.group(1))

        if out.get("letterboxd_rating") or out.get("letterboxd_url"):
            return out
    return {}


# ---------------------------------------------------------------------------
# OMDb (optional): IMDb + Rotten Tomatoes + Metacritic
# ---------------------------------------------------------------------------

def _omdb(imdb_id: str, title: str = "", year: int | None = None) -> dict:
    if not OMDB_KEY:
        return {}
    params = {"apikey": OMDB_KEY}
    if imdb_id:
        params["i"] = imdb_id
    else:
        params["t"] = title
        if year:
            params["y"] = str(year)
    try:
        d = http_json("https://www.omdbapi.com/?" + urllib.parse.urlencode(params))
    except Exception:
        return {}
    if d.get("Response") != "True":
        return {}

    out: dict = {}
    if d.get("imdbRating") and d["imdbRating"] != "N/A":
        out["imdb_rating"] = float(d["imdbRating"])
    if d.get("imdbVotes") and d["imdbVotes"] != "N/A":
        out["imdb_votes"] = int(d["imdbVotes"].replace(",", ""))
    for r in d.get("Ratings") or []:
        src, val = r.get("Source"), r.get("Value", "")
        if src == "Rotten Tomatoes" and val.endswith("%"):
            out["rt_rating"] = int(val[:-1])
        elif src == "Metacritic" and "/" in val:
            out["metacritic"] = int(val.split("/")[0])
    if d.get("imdbID"):
        out["imdb_id"] = d["imdbID"]
    for k_src, k_dst in (("Plot", "overview"), ("Director", "director"),
                         ("Actors", "cast"), ("Country", "country")):
        if d.get(k_src) and d[k_src] != "N/A":
            out.setdefault(k_dst, d[k_src])
    if d.get("Runtime", "").endswith(" min"):
        out["runtime"] = int(d["Runtime"].split()[0])
    return out


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def load_cache(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_cache(path: str, cache: dict):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=1, sort_keys=True)


# Programme decorations that stop a title matching a film database. Repertory
# venues append these constantly: "Lawrence of Arabia - Staff Picks",
# "The Good, The Bad and The Ugly: 60th Anniversary", "Buddy + Q&A".
_DECORATION_RES = [
    re.compile(r"\[[^\]]*\]"),                                   # [LAST SCREENING]
    re.compile(r"\s*\+\s*Q\s*&\s*A.*$", re.I),                   # + Q&A
    re.compile(r"\s*[-–—:]\s*(staff picks?|coups? de c(?:o|œ)eur.*|"
               r"petits modernes|cin[ée]-?club.*|s[ée]ance sp[ée]ciale.*|"
               r"pr[ée]sent[ée].*|en pr[ée]sence.*)$", re.I),
    re.compile(r"\s*[-–—:,]?\s*\d{1,3}\s*(e|er|th|st|nd|rd)?\s*"
               r"(anniversaire|anniversary).*$", re.I),
    re.compile(r"\s*[-–—:]\s*(nouvelle\s+)?(restauration|restored|remaster\w*)"
               r"(\s*\d?k)?\s*$", re.I),
    re.compile(r"\s*\((?:vf|voa|vostf|vosta|vo|2d|3d|imax|4k|dcp)\)\s*$", re.I),
]


def search_title(title: str) -> str:
    """Strip programme decorations so the title can be looked up."""
    t = clean(title)
    for _ in range(3):          # decorations stack: "X - Staff Picks [LAST]"
        before = t
        for rx in _DECORATION_RES:
            t = rx.sub("", t).strip(" -–—:,")
        if t == before:
            break
    return t or clean(title)


def enrich_film(title: str, year: int | None, director: str = "",
                original_title: str = "") -> dict:
    """Look a film up across the sources. Never raises."""
    info: dict = {}
    title = search_title(title)
    original_title = search_title(original_title) if original_title else ""

    # 1. Identity: TMDB when we have a key, Wikidata otherwise.
    ident = _tmdb(original_title or title, year)
    if not ident and original_title and original_title != title:
        ident = _tmdb(title, year)
    if not ident:
        ident = _wikidata_ids(original_title or title, year, director)
        if not ident and original_title and original_title != title:
            ident = _wikidata_ids(title, year, director)
    info.update(ident)

    imdb_id = info.get("imdb_id") or ""
    tmdb_id = info.get("tmdb_id") or ""

    # 2. Letterboxd (priority rating).
    if imdb_id or tmdb_id:
        info.update(_letterboxd(imdb_id, tmdb_id))
        time.sleep(0.4)

    # 3. OMDb for IMDb / Rotten Tomatoes / Metacritic.
    omdb = _omdb(imdb_id, title, year)
    for k, v in omdb.items():
        info.setdefault(k, v)

    info["enriched_at"] = time.strftime("%Y-%m-%d")
    return info


def enrich_all(films: list[dict], cache_path: str, limit: int | None = None) -> dict:
    """films: [{key,title,year,director,original_title}] -> {key: info}"""
    cache = load_cache(cache_path)
    now = time.time()
    todo = []
    for f in films:
        hit = cache.get(f["key"])
        if hit:
            stamp = hit.get("enriched_at", "")
            try:
                age = time.mktime(time.strptime(stamp, "%Y-%m-%d"))
            except Exception:
                age = 0
            resolved = bool(hit.get("imdb_id") or hit.get("tmdb_id"))
            ttl = CACHE_TTL_DAYS if resolved else UNRESOLVED_TTL_DAYS
            if age >= now - ttl * 86400:
                continue
        todo.append(f)

    if limit:
        todo = todo[:limit]
    log(f"[enrich] {len(films)} films, {len(todo)} need lookup "
        f"(tmdb={'yes' if TMDB_KEY else 'no'}, omdb={'yes' if OMDB_KEY else 'no'})")

    for i, f in enumerate(todo, 1):
        try:
            cache[f["key"]] = enrich_film(
                f["title"], f.get("year"), f.get("director", ""), f.get("original_title", "")
            )
        except Exception as e:  # noqa: BLE001
            log(f"[enrich] {f['title']}: {e}")
            cache[f["key"]] = {"enriched_at": time.strftime("%Y-%m-%d")}
        if i % 20 == 0:
            log(f"[enrich] {i}/{len(todo)}")
            save_cache(cache_path, cache)

    save_cache(cache_path, cache)
    return cache
