"""Run every adapter, merge into one dataset, enrich, and write data/.

Usage:
    python3 scrapers/build.py                 # everything
    python3 scrapers/build.py --no-enrich     # skip ratings lookups
    python3 scrapers/build.py --only cinemacinema,ticketacces
    python3 scrapers/build.py --enrich-limit 50
"""

from __future__ import annotations

import argparse
import datetime as dt
import importlib
import json
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
PAGES = os.path.join(ROOT, "pages")
sys.path.insert(0, HERE)

from common import (LANGS, SPECIAL_WEIGHTS, Screening, Venue, clean, derive_tags,
                    lang_bundle, log, merge_i18n, parse_version, title_key,
                    today)  # noqa: E402

ADAPTERS = [
    "cinemacinema",
    "cinemamoderne",
    "ticketacces",
    "cineplex",
    "cinestarz",
    "guzzo",
    "cinematheque",
    "outremont",
]


# The language a source publishes in when it says nothing about it. Anything a
# source *does* say (its own `Screening.i18n`) wins over this.
SOURCE_LANG = {
    "cinemacinema": "fr",
    "cinemamoderne": "fr",
    "ticketacces": "fr",
    "cineplex": "en",
    "cinestarz": "en",
    "guzzo": "fr",
    "cinematheque": "fr",
    "outremont": "fr",
}


def source_lang(source: str) -> str:
    return SOURCE_LANG.get((source or "").split(":")[0], "fr")


def screening_i18n(s: Screening) -> dict:
    """What one listing says, in the language(s) it says it in."""
    return merge_i18n(
        getattr(s, "i18n", None) or {},
        lang_bundle(source_lang(s.source), title=s.title, synopsis=s.synopsis,
                    genres=s.genres, country=s.country),
    )


def run_adapter(name: str):
    mod = importlib.import_module(name)
    return mod.fetch()


def pick(*vals):
    for v in vals:
        if v:
            return v
    return ""


def merge(screenings: list[Screening], venues: dict) -> list[dict]:
    """Group screenings into films keyed by a normalized title."""
    groups: dict[str, list[Screening]] = {}
    for s in screenings:
        # Use the year when we have it so remakes stay distinct.
        k = title_key(s.title)
        if s.year:
            k = f"{k}:{s.year}"
        groups.setdefault(k, []).append(s)

    # Second pass: fold year-less groups into a year-ed group of the same title.
    by_base: dict[str, list[str]] = {}
    for k in groups:
        by_base.setdefault(k.split(":")[0], []).append(k)
    for base, keys in by_base.items():
        if len(keys) < 2:
            continue
        yeared = sorted([k for k in keys if ":" in k])
        bare = [k for k in keys if ":" not in k]
        if len(yeared) == 1 and bare:
            for b in bare:
                groups[yeared[0]].extend(groups.pop(b))

    movies = []
    for key, items in groups.items():
        items.sort(key=lambda s: s.start)
        # Prefer the longest title as display (usually the most descriptive),
        # but the shortest for matching.
        titles = sorted({s.title for s in items}, key=len)
        display = titles[0]
        for s in items:
            if s.source.startswith("cinemacinema") or s.source.startswith("ticketacces"):
                display = s.title
                break

        def best(attr, longest=False):
            vals = [getattr(s, attr) for s in items if getattr(s, attr)]
            if not vals:
                return ""
            return max(vals, key=len) if longest else vals[0]

        years = [s.year for s in items if s.year]
        runtimes = [s.runtime for s in items if s.runtime]
        genres: list[str] = []
        for s in items:
            for g in s.genres:
                if g not in genres:
                    genres.append(g)
        tags: list[str] = []
        for s in items:
            for t in s.tags:
                if t not in tags:
                    tags.append(t)

        # Per-language copy for the whole film: the longest synopsis wins (the
        # venues truncate at different lengths), genres accumulate.
        i18n: dict = {}
        for s in items:
            for lang, vals in screening_i18n(s).items():
                dst = i18n.setdefault(lang, {})
                if vals.get("title") and not dst.get("title"):
                    dst["title"] = vals["title"]
                syn = vals.get("synopsis") or ""
                if syn and len(syn) > len(dst.get("synopsis") or ""):
                    dst["synopsis"] = syn
                for g in vals.get("genres") or []:
                    dst.setdefault("genres", [])
                    if g not in dst["genres"]:
                        dst["genres"].append(g)
                if vals.get("country") and not dst.get("country"):
                    dst["country"] = vals["country"]

        shows = []
        for s in items:
            v = parse_version(s.version_raw)
            ven = venues.get(s.venue_id)
            st_tags = derive_tags(
                title=s.title, fmt=s.fmt, version=s.version_raw, time_=s.time,
                venue_kind=getattr(ven, "kind", ""), venue_chain=getattr(ven, "chain", ""),
                year=years[0] if years else s.year, synopsis=s.synopsis,
                existing=s.tags,
            )
            for tg in st_tags:
                if tg not in tags:
                    tags.append(tg)
            shows.append({
                "venue": s.venue_id,
                "start": s.start,
                "date": s.date,
                "time": s.time,
                "url": s.url,
                "ticket_url": s.ticket_url or s.url,
                "version": v["code"],
                "language": v["language"],
                "subtitles": v["subtitles"],
                "version_label": v["label"],
                "format": s.fmt,
                "room": s.room,
                "source": s.source,
                "tags": list(st_tags),
            })

        movies.append({
            "id": key,
            "title": display,
            "original_title": best("original_title"),
            "year": years[0] if years else None,
            "runtime": runtimes[0] if runtimes else None,
            "genres": genres,
            "synopsis": best("synopsis", longest=True),
            "poster": best("poster"),
            "backdrop": best("backdrop"),
            "director": best("director"),
            "cast": best("cast", longest=True),
            "trailer": best("trailer"),
            "country": best("country"),
            "rating": best("rating"),
            "i18n": i18n,
            "tags": tags,
            "showtimes": shows,
        })

    movies.sort(key=lambda m: (-len(m["showtimes"]), m["title"]))
    return movies


def apply_enrichment(movies: list[dict], cache: dict):
    for m in movies:
        info = cache.get(m["id"]) or {}
        if not info:
            continue
        # Ratings (Letterboxd first, per preference).
        for k in ("letterboxd_rating", "letterboxd_votes", "letterboxd_url",
                  "rt_rating", "imdb_rating", "imdb_votes", "metacritic",
                  "tmdb_rating", "tmdb_votes", "imdb_id", "tmdb_id", "wikidata_id"):
            if info.get(k) is not None and info.get(k) != "":
                m[k] = info[k]
        # Fill metadata gaps only.
        if not m.get("synopsis") and info.get("overview"):
            m["synopsis"] = info["overview"]
        # Backdrop is the exception to "fill gaps only": several venues point at
        # stills on hosts that refuse hotlinking or are unreachable, leaving the
        # hero blank. Letterboxd's CDN always serves, so it wins when we have it.
        if info.get("backdrop"):
            m["backdrop"] = info["backdrop"]
        for src, dst in (("poster", "poster"), ("backdrop", "backdrop"),
                         ("director", "director"), ("cast", "cast"),
                         ("country", "country"), ("runtime", "runtime"),
                         ("year", "year"), ("original_title", "original_title")):
            if not m.get(dst) and info.get(src):
                m[dst] = info[src]
        if info.get("genres") and not m.get("genres"):
            m["genres"] = info["genres"]
        # Translated copy: only ever fills a language the venues left empty, so
        # a cinema's own English synopsis always outranks TMDB's.
        i18n = m.setdefault("i18n", {})
        for lang in LANGS:
            dst = i18n.setdefault(lang, {})
            for src, key in ((f"overview_{lang}", "synopsis"),
                             (f"title_{lang}", "title")):
                if info.get(src) and not dst.get(key):
                    dst[key] = info[src]
            if info.get(f"genres_{lang}") and not dst.get("genres"):
                dst["genres"] = list(info[f"genres_{lang}"])
        m["i18n"] = {k: v for k, v in i18n.items() if v}
        if m.get("imdb_id"):
            m["imdb_url"] = f"https://www.imdb.com/title/{m['imdb_id']}/"


def merge_by_identity(movies: list[dict]) -> list[dict]:
    """Fold together entries that enrichment proved are the same film.

    Venues list the same title in French and in English ("Minions & Monsters"
    vs "Les minions et les monstres"); normalizing the strings cannot reconcile
    those, but a shared IMDb/TMDB id can. The per-showtime version label still
    tells the viewer which print they are buying a ticket for.
    """
    groups: dict[str, list[dict]] = {}
    singles: list[dict] = []
    for m in movies:
        ident = m.get("imdb_id") or (f"tmdb:{m['tmdb_id']}" if m.get("tmdb_id") else "")
        if ident:
            groups.setdefault(ident, []).append(m)
        else:
            singles.append(m)

    out = list(singles)
    for ident, items in groups.items():
        if len(items) == 1:
            out.append(items[0])
            continue
        # Defence in depth: never fold entries whose years genuinely disagree,
        # even if they somehow resolved to the same id.
        years = {m["year"] for m in items if m.get("year")}
        if len(years) > 1 and max(years) - min(years) > 1:
            out.extend(items)
            continue
        # Keep the entry with the most showtimes as the base.
        items.sort(key=lambda m: (-len(m["showtimes"]), m["title"]))
        base = dict(items[0])
        for other in items[1:]:
            base["showtimes"] = base["showtimes"] + other["showtimes"]
            for key in ("genres", "tags"):
                merged = list(base.get(key) or [])
                for v in other.get(key) or []:
                    if v not in merged:
                        merged.append(v)
                base[key] = merged
            for key in ("synopsis", "poster", "backdrop", "director", "cast",
                        "trailer", "country", "rating", "original_title",
                        "year", "runtime"):
                if not base.get(key) and other.get(key):
                    base[key] = other[key]
            # The French listing and the English listing of the same film are
            # exactly what this fold joins, so their copy joins too.
            joined = base.get("i18n") or {}
            for lang, vals in (other.get("i18n") or {}).items():
                dst = joined.setdefault(lang, {})
                for k, v in vals.items():
                    if k == "genres":
                        merged = list(dst.get("genres") or [])
                        for g in v:
                            if g not in merged:
                                merged.append(g)
                        dst["genres"] = merged
                    elif v and not dst.get(k):
                        dst[k] = v
            base["i18n"] = joined
        base["showtimes"].sort(key=lambda s: s["start"])
        base["alt_titles"] = sorted({m["title"] for m in items[1:]} - {base["title"]})
        out.append(base)

    out.sort(key=lambda m: (-len(m["showtimes"]), m["title"]))
    return out


def special_score(m: dict) -> int:
    """How much a cinephile would regret missing this. Drives the radar."""
    score = sum(SPECIAL_WEIGHTS.get(t, 0) for t in m.get("tags", []))
    if "only-screening" in m.get("tags", []):
        score += 9
    elif len(m["showtimes"]) <= 3:
        score += 4
    lb = m.get("letterboxd_rating")
    if lb:
        score += max(0, (lb - 3.2)) * 6          # 4.5 -> +7.8
    return round(score, 2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-enrich", action="store_true")
    ap.add_argument("--enrich-limit", type=int, default=None)
    ap.add_argument("--only", default="")
    args = ap.parse_args()

    names = [n.strip() for n in args.only.split(",") if n.strip()] or ADAPTERS

    all_venues: dict[str, Venue] = {}
    all_screenings: list[Screening] = []
    report = []

    for name in names:
        started = dt.datetime.now()
        try:
            venues, screenings = run_adapter(name)
            for v in venues:
                all_venues.setdefault(v.id, v)
            all_screenings.extend(screenings)
            report.append({
                "source": name, "ok": True, "screenings": len(screenings),
                "venues": len(venues),
                "seconds": round((dt.datetime.now() - started).total_seconds(), 1),
            })
            log(f"[build] {name}: {len(screenings)} screenings")
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            report.append({
                "source": name, "ok": False, "screenings": 0, "venues": 0,
                "error": f"{type(e).__name__}: {e}",
                "seconds": round((dt.datetime.now() - started).total_seconds(), 1),
            })
            log(f"[build] {name} FAILED: {e}")

    if not all_screenings:
        log("[build] no screenings at all — refusing to overwrite data/")
        # Still write the status so the site can show a stale warning.
        os.makedirs(DATA, exist_ok=True)
        with open(os.path.join(DATA, "status.json"), "w", encoding="utf-8") as f:
            json.dump({"generated_at": dt.datetime.now().isoformat(timespec="seconds"),
                       "sources": report, "failed": True}, f, indent=1)
        raise SystemExit(1)

    movies = merge(all_screenings, all_venues)
    log(f"[build] merged into {len(movies)} films")

    os.makedirs(DATA, exist_ok=True)
    cache_path = os.path.join(DATA, "enrich_cache.json")

    if not args.no_enrich:
        import enrich

        films = [{
            "key": m["id"], "title": m["title"], "year": m.get("year"),
            "director": m.get("director", ""), "original_title": m.get("original_title", ""),
            # Runtime is the strongest signal we have for films the cinema
            # lists without a year.
            "runtime": m.get("runtime"),
        } for m in movies]
        cache = enrich.enrich_all(films, cache_path, limit=args.enrich_limit)
        apply_enrichment(movies, cache)
    else:
        apply_enrichment(movies, enrich_cache_safe(cache_path))

    # IMDb ratings come from IMDb's official dataset in one bulk fetch.
    try:
        import enrich as _e
        ids = {m.get("imdb_id") for m in movies if m.get("imdb_id")}
        ratings = _e.imdb_ratings(ids)
        for m in movies:
            r = ratings.get(m.get("imdb_id") or "")
            if r:
                m.update(r)
    except Exception as e:  # noqa: BLE001
        log(f"[build] imdb ratings skipped: {e}")

    before = len(movies)
    movies = merge_by_identity(movies)
    if before != len(movies):
        log(f"[build] folded {before - len(movies)} duplicate titles via IMDb/TMDB ids")

    # A single screening anywhere in the city is the strongest urgency signal
    # there is, so it becomes a tag of its own.
    for m in movies:
        if len(m["showtimes"]) == 1 and "only-screening" not in m["tags"]:
            m["tags"].append("only-screening")
        m["special"] = special_score(m)

    dates = sorted({s["date"] for m in movies for s in m["showtimes"]})
    payload = {
        "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "today": today().isoformat(),
        "date_range": {"first": dates[0] if dates else "", "last": dates[-1] if dates else ""},
        "counts": {
            "movies": len(movies),
            "venues": len(all_venues),
            "showtimes": sum(len(m["showtimes"]) for m in movies),
        },
        "venues": [v.as_dict() for v in sorted(all_venues.values(), key=lambda v: v.name)],
        "movies": movies,
        "sources": report,
    }

    # Crawlable pages first: it assigns each film and venue its permanent slug,
    # which then travels in index.json so the app can link to them.
    try:
        import shutil

        import pages as page_gen
        shutil.rmtree(PAGES, ignore_errors=True)
        os.makedirs(PAGES, exist_ok=True)
        n_pages = page_gen.build(payload, PAGES)
        log(f"[build] generated {n_pages} static pages")
    except Exception as e:  # noqa: BLE001
        log(f"[build] static pages skipped: {e}")

    out = os.path.join(DATA, "index.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(DATA, "status.json"), "w", encoding="utf-8") as f:
        json.dump({"generated_at": payload["generated_at"], "counts": payload["counts"],
                   "sources": report}, f, indent=1, ensure_ascii=False)

    size = os.path.getsize(out) / 1024
    log(f"[build] wrote {out} ({size:.0f} KB): "
        f"{payload['counts']['movies']} films, "
        f"{payload['counts']['showtimes']} showtimes, "
        f"{payload['counts']['venues']} venues")


def enrich_cache_safe(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


if __name__ == "__main__":
    main()
