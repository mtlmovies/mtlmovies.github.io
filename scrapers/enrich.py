"""Film identification, artwork and ratings — entirely without API keys.

    title (+year, +runtime)
        -> TMDB public search / Wikidata      : which film is this, really
        -> themoviedb.org page                : real portrait poster
        -> letterboxd.com/tmdb|imdb/<id>      : Letterboxd rating + IMDb id
        -> IMDb's official ratings dataset    : IMDb rating + votes

Identification is the part that matters. Multiplexes list films with no year,
so a title alone is a dangerous key: "L'Odyssée" matches a 2016 Cousteau
documentary as readily as the 2026 Nolan film playing this week. Every
candidate is therefore checked against the runtime and year the cinema
reported, and rejected when they disagree.
"""

from __future__ import annotations

import datetime as dt
import gzip
import io
import json
import os
import re
import time
import urllib.parse

from common import clean, http_get, http_get_bytes, http_json, log

TMDB_KEY = os.environ.get("TMDB_API_KEY", "").strip()   # optional
OMDB_KEY = os.environ.get("OMDB_API_KEY", "").strip()   # optional

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
TMDB_WEB = "https://www.themoviedb.org"
LETTERBOXD = "https://letterboxd.com"

CACHE_TTL_DAYS = 21
UNRESOLVED_TTL_DAYS = 3

# How far a candidate may differ from what the cinema published.
RUNTIME_TOLERANCE = 10      # minutes
YEAR_TOLERANCE = 1          # years

FILMISH = {"Q11424", "Q24869", "Q506240", "Q202866", "Q93204", "Q29168811"}


# ---------------------------------------------------------------------------
# Title cleanup
# ---------------------------------------------------------------------------

_DECORATIONS = [
    re.compile(r"\[[^\]]*\]"),
    re.compile(r"\s*\+\s*Q\s*&\s*A.*$", re.I),
    re.compile(r"\s*[-–—:]\s*(staff picks?|coups? de c(?:o|œ)eur.*|petits modernes|"
               r"cin[ée]-?club.*|s[ée]ance sp[ée]ciale.*|pr[ée]sent[ée].*|en pr[ée]sence.*)$", re.I),
    re.compile(r"\s*[-–—:,]?\s*\d{1,3}\s*(e|er|th|st|nd|rd)?\s*(anniversaire|anniversary).*$", re.I),
    re.compile(r"\s*[-–—:]\s*(nouvelle\s+)?(restauration|restored|remaster\w*)(\s*\d?k)?\s*$", re.I),
    re.compile(r"\s*\((?:vf|voa|vostf|vosta|vo|2d|3d|imax|4k|dcp)\)\s*$", re.I),
    re.compile(r"\s*\((?:re-?release|reprise)\)\s*$", re.I),
    re.compile(r"\s*\b(w/?e\.?s\.?t\.?|with english subtitles|avec s\.?t\.?f\.?)\b.*$", re.I),
]


def search_title(title: str) -> str:
    """Strip programme decorations so a title can be looked up."""
    t = clean(title)
    for _ in range(3):
        before = t
        for rx in _DECORATIONS:
            t = rx.sub("", t).strip(" -–—:,")
        if t == before:
            break
    return t or clean(title)


def _is_rerelease(title: str) -> bool:
    return bool(re.search(r"anniversar|anniversaire|re-?release|reprise|restaur|classic", title, re.I))


# ---------------------------------------------------------------------------
# Candidate acceptance
# ---------------------------------------------------------------------------

def _accept(cand_year, cand_runtime, want_year, want_runtime, title) -> bool:
    """Would this candidate plausibly be the film the cinema is showing?"""
    if want_year and cand_year and abs(cand_year - want_year) > YEAR_TOLERANCE:
        return False
    if want_runtime and cand_runtime and abs(cand_runtime - want_runtime) > RUNTIME_TOLERANCE:
        return False
    # No year from the venue (typical of multiplexes): a film in wide release is
    # a recent one unless the title itself advertises a revival.
    if not want_year and cand_year and not _is_rerelease(title):
        if cand_year < dt.date.today().year - 2 and not (
            want_runtime and cand_runtime and abs(cand_runtime - want_runtime) <= 3
        ):
            return False
    return True


# ---------------------------------------------------------------------------
# TMDB public website (no key)
# ---------------------------------------------------------------------------

_TMDB_ID_RE = re.compile(r'href="/movie/(\d+)[^"]*"')
_TMDB_RUNTIME_RE = re.compile(r'<span class="runtime">\s*(?:(\d+)h)?\s*(?:(\d+)m)?\s*</span>')
_TMDB_TITLE_RE = re.compile(r"<title>\s*(.*?)\s*\((\d{4})\)\s*&#8212;")


def _tmdb_search(title: str, limit: int = 5) -> list[str]:
    try:
        html = http_get(
            f"{TMDB_WEB}/search/movie?" + urllib.parse.urlencode({"query": title}),
            browser_ua=True, retries=2, timeout=30)
    except Exception:
        return []
    out = []
    for mid in _TMDB_ID_RE.findall(html):
        if mid not in out:
            out.append(mid)
        if len(out) >= limit:
            break
    return out


def _tmdb_page(tmdb_id: str, language: str = "") -> dict:
    """Poster, year and runtime from a TMDB film page.

    `language` asks TMDB for a localized page ("en-US", "fr-CA"): the title,
    the overview and the genre names come back translated, which is where the
    site's English copy comes from for the many venues that publish in French
    only.
    """
    url = f"{TMDB_WEB}/movie/{tmdb_id}"
    if language:
        url += "?" + urllib.parse.urlencode({"language": language})
    try:
        html = http_get(url, browser_ua=True, retries=2, timeout=30)
    except Exception:
        return {}
    out: dict = {"tmdb_id": str(tmdb_id)}

    m = _TMDB_TITLE_RE.search(html)
    if m:
        out["title"] = clean(m.group(1))
        out["year"] = int(m.group(2))

    r = _TMDB_RUNTIME_RE.search(html)
    if r and (r.group(1) or r.group(2)):
        out["runtime"] = int(r.group(1) or 0) * 60 + int(r.group(2) or 0)

    for src in re.findall(r'<meta property="og:image" content="([^"]+)"', html):
        if "/t/p/" in src:
            out["poster"] = src
            break
    d = re.search(r'<meta property="og:description" content="([^"]+)"', html)
    if d:
        out["overview"] = clean(d.group(1))
    genres = []
    for g in _TMDB_GENRE_RE.findall(html):
        g = clean(g)
        if g and g not in genres:
            genres.append(g)
    if genres:
        out["genres"] = genres[:4]
    return out


# TMDB links every genre as /genre/<id>-<slug>/movie, with the localized name
# as the link text.
_TMDB_GENRE_RE = re.compile(r'href="/genre/\d+-[^"]*"[^>]*>([^<]{2,30})</a>')

# TMDB's own locale codes for the two languages the site speaks.
TMDB_LOCALES = {"en": "en-US", "fr": "fr-CA"}
# Bumped when the shape of the translated fields changes, so cached entries
# from before the change are topped up instead of waiting out the 21-day TTL.
I18N_VERSION = 1


def translations(tmdb_id: str) -> dict:
    """Title, overview and genres in both languages for one TMDB film."""
    out: dict = {"i18n_v": I18N_VERSION}
    if not tmdb_id:
        return out
    for lang, locale in TMDB_LOCALES.items():
        page = _tmdb_page(tmdb_id, language=locale)
        if not page:
            continue
        if page.get("title"):
            out[f"title_{lang}"] = page["title"]
        if page.get("overview"):
            out[f"overview_{lang}"] = page["overview"]
        if page.get("genres"):
            out[f"genres_{lang}"] = page["genres"]
        time.sleep(0.25)
    return out


# ---------------------------------------------------------------------------
# Wikidata (no key)
# ---------------------------------------------------------------------------

def _wikidata(title: str, want_year, want_runtime) -> dict:
    for lang in ("en", "fr"):
        try:
            res = http_json(WIKIDATA_API + "?" + urllib.parse.urlencode({
                "action": "wbsearchentities", "search": title, "language": lang,
                "uselang": lang, "type": "item", "limit": 8, "format": "json"}))
        except Exception:
            continue
        qids = [h["id"] for h in res.get("search", [])]
        if not qids:
            continue
        try:
            ents = http_json(WIKIDATA_API + "?" + urllib.parse.urlencode({
                "action": "wbgetentities", "ids": "|".join(qids[:8]),
                "props": "claims", "format": "json"})).get("entities", {})
        except Exception:
            continue

        for qid in qids:
            claims = (ents.get(qid) or {}).get("claims") or {}
            inst = {c.get("mainsnak", {}).get("datavalue", {}).get("value", {}).get("id")
                    for c in claims.get("P31", [])}
            if not (inst & FILMISH):
                continue

            def first(pid):
                for c in claims.get(pid, []):
                    v = c.get("mainsnak", {}).get("datavalue", {}).get("value")
                    if v is not None:
                        return v
                return None

            pub, cyear = first("P577"), None
            if isinstance(pub, dict) and pub.get("time"):
                mm = re.search(r"(\d{4})", pub["time"])
                cyear = int(mm.group(1)) if mm else None

            dur, cruntime = first("P2047"), None
            if isinstance(dur, dict) and dur.get("amount"):
                try:
                    cruntime = int(float(str(dur["amount"]).lstrip("+")))
                except ValueError:
                    cruntime = None

            if not _accept(cyear, cruntime, want_year, want_runtime, title):
                continue

            imdb_id = first("P345") or ""
            tmdb_id = str(first("P4947") or "")
            if not imdb_id and not tmdb_id:
                continue
            return {"imdb_id": imdb_id, "tmdb_id": tmdb_id,
                    "year": cyear, "wikidata_id": qid}
    return {}


# ---------------------------------------------------------------------------
# Identification
# ---------------------------------------------------------------------------

def resolve(title: str, want_year=None, want_runtime=None) -> dict:
    """Identify a film, validating each candidate against year and runtime."""
    info: dict = {}

    # TMDB's search covers current releases that Wikidata has not caught up to.
    for tmdb_id in _tmdb_search(title):
        page = _tmdb_page(tmdb_id)
        if not page:
            continue
        if not _accept(page.get("year"), page.get("runtime"), want_year, want_runtime, title):
            continue
        info.update({k: v for k, v in page.items() if k != "title"})
        break

    if not info.get("tmdb_id"):
        info.update(_wikidata(title, want_year, want_runtime))
        if info.get("tmdb_id") and not info.get("poster"):
            info.update({k: v for k, v in _tmdb_page(info["tmdb_id"]).items()
                         if k not in ("title", "year")})
    return info


# ---------------------------------------------------------------------------
# Letterboxd — the priority rating, plus the IMDb id
# ---------------------------------------------------------------------------

_LB_BLOCK = re.compile(r'"aggregateRating"\s*:\s*\{(.*?)\}', re.S)
_LB_VALUE = re.compile(r'"ratingValue"\s*:\s*([0-9.]+)')
_LB_COUNT = re.compile(r'"ratingCount"\s*:\s*(\d+)')
_LB_REVIEWS = re.compile(r'"reviewCount"\s*:\s*(\d+)')


def letterboxd(imdb_id: str = "", tmdb_id: str = "") -> dict:
    for path in (f"/tmdb/{tmdb_id}/" if tmdb_id else "", f"/imdb/{imdb_id}/" if imdb_id else ""):
        if not path:
            continue
        try:
            html = http_get(LETTERBOXD + path, browser_ua=True, retries=2, timeout=30)
        except Exception:
            continue

        out: dict = {}
        u = re.search(r'<meta property="og:url" content="([^"]+)"', html)
        if u:
            out["letterboxd_url"] = u.group(1)

        block = _LB_BLOCK.search(html)
        scope = block.group(1) if block else html
        v = _LB_VALUE.search(scope)
        if v:
            out["letterboxd_rating"] = float(v.group(1))
        else:
            tw = re.search(r'name="twitter:data2" content="([0-9.]+) out of 5"', html)
            if tw:
                out["letterboxd_rating"] = float(tw.group(1))
        c = _LB_COUNT.search(scope) or _LB_REVIEWS.search(scope)
        if c:
            out["letterboxd_votes"] = int(c.group(1))

        # Letterboxd links out to both databases — the cheapest imdb_id we get.
        i = re.search(r"imdb\.com/title/(tt\d+)", html)
        if i:
            out["imdb_id"] = i.group(1)

        # 16:9 still, used for the hero and detail header.
        ogi = re.search(r'<meta property="og:image" content="([^"]+)"', html)
        if ogi and "ltrbxd.com" in ogi.group(1) and "empty-poster" not in ogi.group(1):
            out["backdrop"] = ogi.group(1)

        if out.get("letterboxd_rating") or out.get("letterboxd_url"):
            return out
    return {}


# ---------------------------------------------------------------------------
# OMDb (only if a key happens to be present) — Rotten Tomatoes / Metacritic
# ---------------------------------------------------------------------------

def _omdb(imdb_id: str) -> dict:
    if not OMDB_KEY or not imdb_id:
        return {}
    try:
        d = http_json("https://www.omdbapi.com/?" + urllib.parse.urlencode(
            {"apikey": OMDB_KEY, "i": imdb_id}))
    except Exception:
        return {}
    if d.get("Response") != "True":
        return {}
    out: dict = {}
    for r in d.get("Ratings") or []:
        if r.get("Source") == "Rotten Tomatoes" and r.get("Value", "").endswith("%"):
            out["rt_rating"] = int(r["Value"][:-1])
        elif r.get("Source") == "Metacritic" and "/" in r.get("Value", ""):
            out["metacritic"] = int(r["Value"].split("/")[0])
    return out


# ---------------------------------------------------------------------------
# IMDb ratings — official dataset, no key and no scraping
# ---------------------------------------------------------------------------

IMDB_RATINGS_URL = "https://datasets.imdbws.com/title.ratings.tsv.gz"


def imdb_ratings(wanted: set[str]) -> dict[str, dict]:
    wanted = {w for w in wanted if w}
    if not wanted:
        return {}
    try:
        raw = http_get_bytes(IMDB_RATINGS_URL, timeout=180, retries=2)
    except Exception as e:  # noqa: BLE001
        log(f"[enrich] imdb dataset unavailable: {e}")
        return {}
    out: dict[str, dict] = {}
    try:
        with gzip.open(io.BytesIO(raw), "rt", encoding="utf-8") as f:
            next(f, None)
            for line in f:
                tconst, _, rest = line.partition("\t")
                if tconst not in wanted:
                    continue
                avg, _, votes = rest.partition("\t")
                try:
                    out[tconst] = {"imdb_rating": float(avg), "imdb_votes": int(votes.strip())}
                except ValueError:
                    continue
                if len(out) == len(wanted):
                    break
    except Exception as e:  # noqa: BLE001
        log(f"[enrich] imdb dataset parse failed: {e}")
        return {}
    log(f"[enrich] imdb ratings matched {len(out)}/{len(wanted)}")
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


def enrich_film(title: str, year=None, director: str = "", original_title: str = "",
                runtime=None) -> dict:
    """Identify one film and gather its artwork and ratings. Never raises."""
    info: dict = {}
    queries = [q for q in dict.fromkeys(
        [search_title(original_title or ""), search_title(title)]) if q]

    for q in queries:
        info = resolve(q, year, runtime)
        if info.get("tmdb_id") or info.get("imdb_id"):
            break

    if info.get("tmdb_id") or info.get("imdb_id"):
        lb = letterboxd(info.get("imdb_id", ""), info.get("tmdb_id", ""))
        for k, v in lb.items():
            # An id we already resolved is more trustworthy than a scraped link.
            if k == "imdb_id":
                info.setdefault(k, v)
            else:
                info[k] = v
        time.sleep(0.35)

    for k, v in _omdb(info.get("imdb_id", "")).items():
        info.setdefault(k, v)

    if info.get("tmdb_id"):
        info.update(translations(info["tmdb_id"]))

    info["enriched_at"] = time.strftime("%Y-%m-%d")
    return info


def backfill_translations(cache: dict, keys: list[str], limit: int | None = None) -> int:
    """Add the translated copy to entries identified before it existed.

    Two page reads per film, against films we have already identified — far
    cheaper than expiring the whole cache to pick the new fields up.
    """
    todo = [k for k in keys
            if (cache.get(k) or {}).get("tmdb_id")
            and (cache.get(k) or {}).get("i18n_v") != I18N_VERSION]
    if limit:
        todo = todo[:limit]
    if not todo:
        return 0
    log(f"[enrich] translating {len(todo)} films")
    done = 0
    for k in todo:
        try:
            cache[k].update(translations(cache[k]["tmdb_id"]))
            done += 1
        except Exception as e:  # noqa: BLE001
            log(f"[enrich] translate {k}: {e}")
    return done


def enrich_all(films: list[dict], cache_path: str, limit: int | None = None) -> dict:
    cache = load_cache(cache_path)
    now = time.time()
    todo = []
    for f in films:
        hit = cache.get(f["key"])
        if hit:
            try:
                age = time.mktime(time.strptime(hit.get("enriched_at", ""), "%Y-%m-%d"))
            except Exception:
                age = 0
            resolved = bool(hit.get("imdb_id") or hit.get("tmdb_id"))
            ttl = CACHE_TTL_DAYS if resolved else UNRESOLVED_TTL_DAYS
            if age >= now - ttl * 86400:
                continue
        todo.append(f)

    if limit:
        todo = todo[:limit]
    log(f"[enrich] {len(films)} films, {len(todo)} need lookup")

    for i, f in enumerate(todo, 1):
        try:
            cache[f["key"]] = enrich_film(
                f["title"], f.get("year"), f.get("director", ""),
                f.get("original_title", ""), f.get("runtime"))
        except Exception as e:  # noqa: BLE001
            log(f"[enrich] {f['title']}: {e}")
            cache[f["key"]] = {"enriched_at": time.strftime("%Y-%m-%d")}
        if i % 20 == 0:
            log(f"[enrich] {i}/{len(todo)}")
            save_cache(cache_path, cache)

    backfill_translations(cache, [f["key"] for f in films])
    save_cache(cache_path, cache)
    return cache
