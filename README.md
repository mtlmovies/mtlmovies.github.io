# 🎞️ Montréal Cinéma

**https://mtlmovies.github.io**

A **completely serverless** aggregator of cinema showtimes across Greater Montréal —
built for people who want to see classics on a big screen and support local rooms.

Every day at **05:00 America/Toronto**, a GitHub Action scrapes each cinema,
enriches the films with **Letterboxd / IMDb / Rotten Tomatoes** ratings, commits the
result to `data/`, and redeploys a static site to GitHub Pages. No server, no database.

---

## What it does

- **Browse by day** — a 3-week day strip; every showtime for the selected date.
- **Find a film** — search by title, director or actor, then see *every* room
  screening it, grouped by cinema and day.
- **Filters that matter to a film nerd** — classics, restorations, **35 mm / 70 mm
  projections**, independent cinemas only, version (VF / VOA / subtitled),
  neighbourhood, genre, cinema, single-screening-only.
- **Bilingual listings** — every film carries per-language copy (title, synopsis,
  genres). Cinemas that publish both languages are read in both; anything they
  publish in one language only is topped up from TMDB in the other. The page
  shows your language and falls back to the other rather than to nothing.
- **Ratings** — Letterboxd first (as requested), then Rotten Tomatoes, IMDb, Metacritic.
- **Links back to the source** — every showtime links to the cinema's own page or
  its ticketing checkout, so the sale goes to the cinema.
- **Where it's playing** — each film lists the rooms screening it as tags, and
  every cinema links out to its location on Google Maps.
- Trailer, synopsis, director, cast, country, runtime, age rating, original title.
- Dark/light theme, keyboard `/` to search, deep links (`#film=<id>`).

## Venues covered

| Cinema | Source | How |
|---|---|---|
| **Cinéma du Parc** | cinemacinema.ca | SvelteKit `__data.json` |
| **Cinéma Beaubien** | cinemacinema.ca | SvelteKit `__data.json` |
| **Cinéma du Musée** | cinemacinema.ca | SvelteKit `__data.json` |
| **Cinéma Moderne** | cinemamoderne.com (TicketAcces fallback) | month calendar HTML |
| **Cinéma Public** (Casa d'Italia + Le Livart) | TicketAcces | server-rendered HTML |
| **Cinéma Banque Scotia**, **Forum**, **Quartier Latin**, **Starcité**, **Carrefour Angrignon**, **Royalmount**, **Kirkland**, **Laval**, **Brossard**, **Saint-Bruno**, **Vaudreuil** | Cineplex public API | JSON |
| **Ciné Starz** ×7 (Côte-des-Neiges, Cavendish, Des Sources, Lacordaire, Saint-Laurent, Longueuil, Taschereau) | cinestarz.ca | HTML |
| **Cinémas Guzzo — Méga-Plex Terrebonne 14** | cinemasguzzo.com | HTML |
| **Cinémathèque québécoise**, **Théâtre Outremont** | own sites | best-effort (see below) |

> **Cinémathèque québécoise and Théâtre Outremont do not publish screening times
> in HTML.** Both are reachable from GitHub runners, and their pages are parsed on
> every run, but the Cinémathèque publishes its grid only as a monthly PDF and
> Outremont's programme carries no times in markup. They are reported as skipped
> in `data/status.json`, in the Action summary and in the site footer, and will
> start working unchanged if either publishes times. Everything else still builds.
>
> Run `scrapers/probe.py` to see what a given network can reach, and the
> **Dump source HTML** workflow to pull a venue's real markup down as an artifact
> for parser work (several venues reset connections from non-runner networks).

## Run it locally

```bash
# Full refresh (scrapes everything, then looks up ratings)
python3 scrapers/build.py

# Fast: skip the ratings lookups
python3 scrapers/build.py --no-enrich

# Just one or two sources
python3 scrapers/build.py --only cinemacinema,ticketacces

# What can this network actually reach?
python3 scrapers/probe.py
```

### Previewing the site locally

The page loads `./data/index.json` relative to itself, and browsers block
`fetch()` on `file://` URLs — so **opening `site/index.html` from Finder shows an
empty page**. Serve it over HTTP instead:

```bash
ln -sfn ../data site/data          # once; git-ignored, only for local preview
python3 -m http.server -d site 8000
# → http://localhost:8000
```

The deploy does the same thing differently: the workflow copies `site/*` and
`data/*.json` into `_site/` before publishing.

## Ratings enrichment

Works with **no API keys at all**:

```
title (+year) → Wikidata → imdb_id / tmdb_id → Letterboxd film page → rating
```

Two optional secrets improve it (set them in *Settings → Secrets → Actions*):

| Secret | Adds |
|---|---|
| `TMDB_API_KEY` | better title matching, backdrops, overviews, TMDB score |
| `OMDB_API_KEY` | IMDb rating, **Rotten Tomatoes**, Metacritic |

It also reads each film's TMDB page once per language (`en-US`, `fr-CA`), which
is where the English copy comes from for the many venues that publish in French
only. Lookups are cached in `data/enrich_cache.json` (committed) and refreshed
every 21 days, so a daily run only looks up films it has never seen; entries
cached before the translations existed are topped up in place.

## Automation

`.github/workflows/refresh.yml`

- **Daily at 05:00 Montréal** (two crons so it lands at 5am in both EST and EDT).
- **Manually runnable** — *Actions → Refresh showtimes & deploy → Run workflow*,
  with optional `skip_enrichment` and `only` inputs.
- **On push to `main`** touching `site/**` — redeploys the site without re-scraping.
- Commits refreshed data back to `main`, then deploys to GitHub Pages.

### First-time setup

1. **Settings → Pages → Source: GitHub Actions.**
2. (Optional) add `TMDB_API_KEY` / `OMDB_API_KEY` secrets.
3. Run the workflow once manually to populate `data/`.

## Layout

```
scrapers/
  common.py        HTTP, version/time parsing, Venue + Screening models
  cinemacinema.py  Parc · Beaubien · Musée
  cinemamoderne.py Cinéma Moderne (own calendar)
  ticketacces.py   Cinéma Public (+ Moderne fallback)
  cineplex.py      Cineplex circuit
  cinestarz.py     Ciné Starz
  guzzo.py         Guzzo Terrebonne
  cinematheque.py  Cinémathèque · Outremont (best-effort)
  enrich.py        Wikidata → Letterboxd / OMDb / TMDB
  build.py         orchestrator → data/index.json
  probe.py         reachability diagnostics
site/              index.html · app.js · styles.css (no build step)
data/              generated: index.json, status.json, enrich_cache.json
```

Adding a cinema = one module exporting `fetch() -> (list[Venue], list[Screening])`,
plus its name in `ADAPTERS` in `build.py`. A source that throws is reported and
skipped; it never takes the build down.

## Notes on scraping

One pass per day, sequential, with small delays between requests. Adapters send a
descriptive User-Agent by default and only fall back to a browser UA for hosts that
reject unknown agents. Showtime links always point back to the cinema's own page or
checkout — this is meant to send people *to* the cinemas.

Data belongs to the respective cinemas; ratings to Letterboxd / IMDb / Rotten
Tomatoes / TMDB. This project is a personal, non-commercial index.
