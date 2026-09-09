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
sys.path.insert(0, HERE)

from common import Screening, Venue, clean, log, parse_version, title_key, today  # noqa: E402

ADAPTERS = [
    "cinemacinema",
    "cinemamoderne",
    "ticketacces",
    "cineplex",
    "cinestarz",
    "guzzo",
    "cinematheque",
]


def run_adapter(name: str):
    mod = importlib.import_module(name)
    return mod.fetch()


def pick(*vals):
    for v in vals:
        if v:
            return v
    return ""


def merge(screenings: list[Screening]) -> list[dict]:
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

        shows = []
        for s in items:
            v = parse_version(s.version_raw)
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
                "tags": list(s.tags),
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
        for src, dst in (("poster", "poster"), ("backdrop", "backdrop"),
                         ("director", "director"), ("cast", "cast"),
                         ("country", "country"), ("runtime", "runtime"),
                         ("year", "year"), ("original_title", "original_title")):
            if not m.get(dst) and info.get(src):
                m[dst] = info[src]
        if info.get("genres") and not m.get("genres"):
            m["genres"] = info["genres"]
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
        base["showtimes"].sort(key=lambda s: s["start"])
        base["alt_titles"] = sorted({m["title"] for m in items[1:]} - {base["title"]})
        out.append(base)

    out.sort(key=lambda m: (-len(m["showtimes"]), m["title"]))
    return out


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

    movies = merge(all_screenings)
    log(f"[build] merged into {len(movies)} films")

    os.makedirs(DATA, exist_ok=True)
    cache_path = os.path.join(DATA, "enrich_cache.json")

    if not args.no_enrich:
        import enrich

        films = [{
            "key": m["id"], "title": m["title"], "year": m.get("year"),
            "director": m.get("director", ""), "original_title": m.get("original_title", ""),
        } for m in movies]
        cache = enrich.enrich_all(films, cache_path, limit=args.enrich_limit)
        apply_enrichment(movies, cache)
    else:
        apply_enrichment(movies, enrich_cache_safe(cache_path))

    before = len(movies)
    movies = merge_by_identity(movies)
    if before != len(movies):
        log(f"[build] folded {before - len(movies)} duplicate titles via IMDb/TMDB ids")

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
