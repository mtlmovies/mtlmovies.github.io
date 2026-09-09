"""Cinéma Moderne — from the cinema's own schedule.

Their site publishes a month-at-a-time calendar as plain HTML with a
`data-day="YYYY-MM-DD"` attribute per day, and a card per screening carrying
director, country, year, runtime, spoken language, subtitles and — the part a
repertory audience actually cares about — the projection format ("DCP - 4K
Restoration", "35mm").

The site sits behind a WAF that resets connections from some networks. When it
cannot be reached we fall back to their TicketAcces programme, which carries the
same screenings with slightly thinner metadata.
"""

from __future__ import annotations

import datetime as dt
import re

from common import Screening, Venue, clean, http_get, log, parse_time, strip_html, today

BASE = "https://www.cinemamoderne.com"
MONTHS_AHEAD = 3

VENUE = Venue(
    id="moderne",
    name="Cinéma Moderne",
    short_name="Moderne",
    address="5150 boulevard Saint-Laurent",
    neighbourhood="Mile End",
    lat=45.5231, lng=-73.5977,
    url=f"{BASE}/horaire/",
    kind="repertory",
    source="cinemamoderne",
)

DAY_RE = re.compile(
    r'data-day="(\d{4}-\d{2}-\d{2})"(.*?)(?=data-day="\d{4}-\d{2}-\d{2}"|</section|<footer)', re.S
)
EVENT_RE = re.compile(
    r'<div class="cm-Cal__day__event">(.*?)(?=<div class="cm-Cal__day__event">|\Z)', re.S
)
TITLE_A_RE = re.compile(r'<a\s+href="([^"]+)"[^>]*>(.*?)</a>', re.S)
FAT_RE = re.compile(r'<span class="cm-Fat">([^<]+)</span>', re.S)
LIST_RE = re.compile(r"<div class='cm-List cm-List--horizontal'[^>]*>(.*?)</div>", re.S)
ITEM_RE = re.compile(r"<span class='cm-List__item'><span>(.*?)</span></span>", re.S)
TICKET_RE = re.compile(r'<a class="cm-CTA cm-CTA--red"[^>]*href="([^"]+)"', re.S)
IMG_RE = re.compile(r'data-bg="([^"]+)"', re.S)
SUBTITLE_RE = re.compile(r'<span class="cm-Card__subtitles">\s*\((.*?)\)\s*</span>', re.S)

FORMAT_WORDS = ("dcp", "35mm", "35 mm", "16mm", "16 mm", "70mm", "blu-ray", "bluray",
                "vhs", "digital", "restoration", "restauration", "4k", "2k")
LANG_WORDS = ("english", "french", "français", "anglais", "spanish", "german", "italian",
              "japanese", "russian", "mandarin", "cantonese", "portuguese", "korean",
              "arabic", "hebrew", "polish", "swedish", "danish", "dutch", "hindi",
              "armenian", "azerbaijani", "georgian", "turkish", "greek", "persian",
              "silent", "muet", "no dialogue")


def _classify(items: list[str]) -> dict:
    """The card's inline list is positional-ish but not fixed; sniff each item."""
    out = {"director": "", "country": "", "year": None, "runtime": None,
           "language": "", "subtitles": "", "format": ""}
    langs: list[str] = []
    for i, raw in enumerate(items):
        v = clean(raw)
        if not v:
            continue
        low = v.lower()
        if re.fullmatch(r"(19|20)\d{2}", v):
            out["year"] = int(v)
            continue
        m = re.match(r"(\d+)\s*(minutes|min)", low)
        if m:
            out["runtime"] = int(m.group(1))
            continue
        if any(w in low for w in FORMAT_WORDS):
            out["format"] = v
            continue
        if any(w in low for w in LANG_WORDS):
            langs.append(v)
            continue
        if i == 0:
            out["director"] = v
        elif not out["country"]:
            out["country"] = v
    if langs:
        out["language"] = langs[0]
        if len(langs) > 1:
            out["subtitles"] = langs[1]
    return out


def _version_code(spoken: str, subs: str, paren: str) -> str:
    """Build a Quebec-style version code the shared parser understands."""
    if paren:
        p = paren.strip().upper()
        if re.fullmatch(r"V[OF][A-Z]*", p.replace(" ", "")):
            return p
    s, sub = (spoken or "").lower(), (subs or "").lower()
    if not s:
        return paren or ""
    english = s.startswith("english")
    french = s.startswith("french") or "français" in s
    if french and not sub:
        return "VF"
    if english and "french" in sub:
        return "VOA STF"
    if english and not sub:
        return "VOA"
    if "french" in sub:
        return "VOSTF"
    if "english" in sub:
        return "VOSTA"
    return paren or ""


def _parse_month(html: str) -> list[Screening]:
    out: list[Screening] = []
    horizon = today() + dt.timedelta(days=150)

    for date_s, chunk in DAY_RE.findall(html):
        try:
            d = dt.date.fromisoformat(date_s)
        except ValueError:
            continue
        if d < today() or d > horizon:
            continue

        for block in EVENT_RE.findall(chunk):
            fat = FAT_RE.search(block)
            if not fat:
                continue
            hm = parse_time(clean(fat.group(1)))
            if not hm:
                continue

            a = TITLE_A_RE.search(block)
            film_url, inner = (a.group(1), a.group(2)) if a else ("", block)
            text = strip_html(FAT_RE.sub(" ", inner))
            title = clean(text.split("\n")[0]) if text else ""
            paren = ""
            pm = re.search(r"\(([^()]{1,24})\)\s*$", title)
            if pm:
                paren = pm.group(1)
                title = title[: pm.start()].strip()
            if not paren:
                sm = SUBTITLE_RE.search(block)
                if sm:
                    paren = clean(sm.group(1))
            if not title:
                continue

            tags = []
            lm = re.search(r"\[([^\]]+)\]", title)
            if lm:
                note = lm.group(1).lower()
                if "last" in note or "derni" in note:
                    tags.append("last-chance")
                title = (title[: lm.start()] + title[lm.end():]).strip(" -–—")

            meta = {}
            lst = LIST_RE.search(block)
            if lst:
                meta = _classify(ITEM_RE.findall(lst.group(1)))

            fmt = meta.get("format", "")
            low_fmt = fmt.lower()
            if "restor" in low_fmt or "restaur" in low_fmt or "4k" in low_fmt:
                tags.append("restoration")
            if "35" in low_fmt or "16mm" in low_fmt or "70" in low_fmt:
                tags.append("celluloid")
            year = meta.get("year")
            if year and year < today().year - 12:
                tags.append("classic")

            tm = TICKET_RE.search(block)
            im = IMG_RE.search(block)

            out.append(Screening(
                venue_id=VENUE.id,
                title=title,
                start=f"{date_s}T{hm[0]:02d}:{hm[1]:02d}",
                date=date_s,
                time=f"{hm[0]:02d}:{hm[1]:02d}",
                url=film_url or VENUE.url,
                ticket_url=tm.group(1) if tm else "",
                version_raw=_version_code(meta.get("language", ""), meta.get("subtitles", ""), paren),
                fmt=fmt,
                year=year,
                runtime=meta.get("runtime"),
                director=meta.get("director", ""),
                country=meta.get("country", ""),
                backdrop=im.group(1) if im else "",
                source="cinemamoderne",
                tags=tuple(dict.fromkeys(tags)),
            ))
    return out


def fetch() -> tuple[list[Venue], list[Screening]]:
    screenings: list[Screening] = []
    errors = []
    start = today().replace(day=1)

    for i in range(MONTHS_AHEAD):
        y, m = start.year, start.month + i
        y, m = y + (m - 1) // 12, (m - 1) % 12 + 1
        url = f"{BASE}/en/schedule/{y}/{m:02d}/"
        try:
            html = http_get(url, retries=2 if i == 0 else 1, timeout=25)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{y}-{m:02d}: {e}")
            log(f"[moderne] {url}: {e}")
            if i == 0:
                # The site is unreachable from this network; don't spend a
                # minute per month proving it — go straight to the fallback.
                break
            continue
        got = _parse_month(html)
        screenings.extend(got)
        log(f"[moderne] {y}-{m:02d}: {len(got)} showtimes")

    if not screenings:
        # Their ticketing platform answers from networks the site itself blocks.
        log(f"[moderne] own site unavailable ({'; '.join(errors)[:160]}), using TicketAcces")
        import ticketacces

        _, fallback = ticketacces.fetch_org("moderne")
        if not fallback:
            raise RuntimeError("; ".join(errors) or "no showtimes")
        return [VENUE], fallback

    # De-duplicate: the calendar repeats an event in its collapsed card markup.
    seen = set()
    unique = []
    for s in screenings:
        k = (s.date, s.time, s.title.lower())
        if k in seen:
            continue
        seen.add(k)
        unique.append(s)
    return [VENUE], unique
