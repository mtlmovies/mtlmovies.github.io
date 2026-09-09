"""Shared plumbing for every cinema adapter.

Each adapter exports `fetch() -> list[Screening]` and is allowed to fail: the
orchestrator in build.py records the failure and keeps the other sources.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import gzip
import hashlib
import io
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import zlib

MONTREAL_TZ = "America/Toronto"

# A descriptive UA by default: we identify ourselves and scrape once a day.
USER_AGENT = (
    "montreal-cinema-index/1.0 (+https://github.com/RodolpheKouyoumdjian/mtlmovies)"
)
# Some venues sit behind WAFs that reject unknown agents outright. For those we
# fall back to a browser UA rather than dropping the venue entirely.
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def log(*args):
    print(*args, file=sys.stderr, flush=True)


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

def http_get(
    url: str,
    *,
    headers: dict | None = None,
    timeout: int = 45,
    retries: int = 3,
    browser_ua: bool = False,
    encoding: str | None = None,
) -> str:
    """GET a URL and return text. Raises on final failure."""
    raw = http_get_bytes(
        url, headers=headers, timeout=timeout, retries=retries, browser_ua=browser_ua
    )
    if encoding:
        return raw.decode(encoding, errors="replace")
    # Try utf-8, fall back to latin-1 (several Quebec sites are ISO-8859-1).
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("iso-8859-1", errors="replace")


def http_get_bytes(
    url: str,
    *,
    headers: dict | None = None,
    timeout: int = 45,
    retries: int = 3,
    browser_ua: bool = False,
) -> bytes:
    hdrs = {
        "User-Agent": BROWSER_UA if browser_ua else USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
        "Accept-Language": "fr-CA,fr;q=0.9,en-CA;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate",
    }
    if headers:
        hdrs.update(headers)

    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = r.read()
                enc = (r.headers.get("Content-Encoding") or "").lower()
                if enc == "gzip":
                    data = gzip.decompress(data)
                elif enc == "deflate":
                    try:
                        data = zlib.decompress(data)
                    except zlib.error:
                        data = zlib.decompress(data, -zlib.MAX_WBITS)
                return data
        except Exception as e:  # noqa: BLE001 - we retry everything
            last = e
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"GET {url} failed after {retries} tries: {last}")


def http_json(url: str, **kw):
    return json.loads(http_get(url, **kw))


# --------------------------------------------------------------------------
# Text helpers
# --------------------------------------------------------------------------

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def strip_html(s: str | None) -> str:
    if not s:
        return ""
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", s)
    s = re.sub(r"(?i)<br\s*/?>", "\n", s)
    s = re.sub(r"(?i)</(p|div|li|h[1-6])>", "\n", s)
    s = _TAG_RE.sub(" ", s)
    s = unescape(s)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n\s*\n\s*\n+", "\n\n", s)
    return s.strip()


def unescape(s: str) -> str:
    import html

    return html.unescape(s).replace("\xa0", " ")


def clean(s: str | None) -> str:
    if not s:
        return ""
    return _WS_RE.sub(" ", unescape(_TAG_RE.sub(" ", s))).strip()


def slugify(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s or "x"


def title_key(title: str, year=None) -> str:
    """Normalized key used to merge the same film across cinemas."""
    t = unicodedata.normalize("NFKD", title or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    # Drop common decorations that differ between venues.
    t = re.sub(r"\(.*?\)", " ", t)
    t = re.sub(
        r"\b(v\.?o\.?a?|v\.?f\.?|vostf|vosta|stf|sta|imax|3d|2d|4k|dcp|"
        r"version francaise|version originale|encore|anniversaire|anniversary)\b",
        " ",
        t,
    )
    t = re.sub(r"[^a-z0-9]+", "", t)
    return t or slugify(title)


def digest(*parts) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:12]


# --------------------------------------------------------------------------
# Language / version normalization (very Montreal-specific)
# --------------------------------------------------------------------------

def parse_version(raw: str | None) -> dict:
    """Turn a Quebec version code into {code, language, subtitles, label}.

    Handles VOA, VF, VOSTF, VOSTA, VOASTF, "Version originale anglaise", etc.
    """
    s = clean(raw).upper().replace(".", "").replace("-", " ")
    s = _WS_RE.sub(" ", s)
    if not s:
        return {"code": "", "language": "", "subtitles": "", "label": ""}

    lang = ""
    subs = ""

    # Long-form French descriptions first.
    if "ORIGINALE ANGLAISE" in s or "ORIGINAL ENGLISH" in s:
        lang = "en"
    elif "ORIGINALE FRANCAISE" in s or "ORIGINALE FRANÇAISE" in s:
        lang = "fr"
    elif "VERSION FRANCAISE" in s or "VERSION FRANÇAISE" in s or s.startswith("VF"):
        lang = "fr"

    if "SOUS TITRES FRANCAIS" in s or "SOUS TITRÉS FRANÇAIS" in s or "STF" in s:
        subs = "fr"
    if "SOUS TITRES ANGLAIS" in s or "ENGLISH SUBTITLES" in s or "STA" in s:
        subs = "en"

    # Compact codes.
    if not lang:
        if re.search(r"\bVOA", s):
            lang = "en"
        elif re.search(r"\bVOF", s):
            lang = "fr"
        elif re.search(r"\bVF\b", s):
            lang = "fr"
        elif re.search(r"\bVO\b|\bVOST", s):
            lang = "vo"
    if not subs:
        if "VOSTF" in s or "VOSTFR" in s:
            lang = lang or "vo"
            subs = "fr"
        elif "VOSTA" in s:
            lang = lang or "vo"
            subs = "en"

    if not lang and ("ENGLISH" in s or s == "EN"):
        lang = "en"
    if not lang and ("FRENCH" in s or "FRANCAIS" in s or s == "FR"):
        lang = "fr"

    label_map = {
        ("en", ""): "English",
        ("en", "fr"): "English, French subtitles",
        ("en", "en"): "English subtitles",
        ("fr", ""): "French",
        ("fr", "en"): "French, English subtitles",
        ("vo", "fr"): "Original w/ French subtitles",
        ("vo", "en"): "Original w/ English subtitles",
        ("vo", ""): "Original version",
    }
    label = label_map.get((lang, subs)) or clean(raw)
    return {"code": clean(raw), "language": lang, "subtitles": subs, "label": label}


# --------------------------------------------------------------------------
# Time helpers
# --------------------------------------------------------------------------

_TIME_PATTERNS = [
    # "14 h 20", "14h20", "14 h"
    (re.compile(r"^(\d{1,2})\s*h\s*(\d{2})?$", re.I), lambda m: (int(m.group(1)), int(m.group(2) or 0))),
    # "14:20"
    (re.compile(r"^(\d{1,2}):(\d{2})$"), lambda m: (int(m.group(1)), int(m.group(2)))),
    # "2:20 PM"
    (
        re.compile(r"^(\d{1,2}):(\d{2})\s*([ap])\.?m\.?$", re.I),
        lambda m: (
            (int(m.group(1)) % 12) + (12 if m.group(3).lower() == "p" else 0),
            int(m.group(2)),
        ),
    ),
]


def parse_time(raw: str | None):
    """Return (hour, minute) or None."""
    s = clean(raw).replace(" ", " ")
    s = _WS_RE.sub(" ", s).strip()
    for pat, fn in _TIME_PATTERNS:
        m = pat.match(s)
        if m:
            h, mi = fn(m)
            if 0 <= h <= 23 and 0 <= mi <= 59:
                return h, mi
    return None


FR_MONTHS = {
    "jan": 1, "fev": 2, "fév": 2, "mar": 3, "avr": 4, "mai": 5, "jui": 6,
    "juin": 6, "juil": 7, "aou": 8, "aoû": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12, "déc": 12,
}
EN_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def month_from_name(name: str):
    k = (name or "").strip().lower()[:4]
    for table in (FR_MONTHS, EN_MONTHS):
        for pref, num in table.items():
            if k.startswith(pref):
                return num
    return None


def today() -> dt.date:
    """Today in Montreal."""
    try:
        from zoneinfo import ZoneInfo

        return dt.datetime.now(ZoneInfo(MONTREAL_TZ)).date()
    except Exception:
        return dt.date.today()


# --------------------------------------------------------------------------
# Data model
# --------------------------------------------------------------------------

@dataclasses.dataclass
class Venue:
    id: str
    name: str
    short_name: str = ""
    address: str = ""
    city: str = "Montréal"
    neighbourhood: str = ""
    lat: float | None = None
    lng: float | None = None
    url: str = ""
    chain: str = "independent"   # independent | cineplex | guzzo | cinestarz
    kind: str = "repertory"      # repertory | arthouse | multiplex | museum
    source: str = ""

    def as_dict(self):
        return dataclasses.asdict(self)


@dataclasses.dataclass
class Screening:
    """One showtime at one venue."""

    venue_id: str
    title: str
    start: str                    # ISO local datetime "2026-09-08T18:15"
    date: str = ""                # "2026-09-08"
    time: str = ""                # "18:15"
    url: str = ""                 # link to the original posting / ticketing
    ticket_url: str = ""
    version_raw: str = ""
    fmt: str = ""                 # 2D / 3D / IMAX / 35mm / 4K ...
    room: str = ""
    # Film metadata, best-effort per source
    original_title: str = ""
    year: int | None = None
    runtime: int | None = None
    genres: tuple = ()
    synopsis: str = ""
    poster: str = ""
    backdrop: str = ""
    director: str = ""
    cast: str = ""
    trailer: str = ""
    country: str = ""
    rating: str = ""              # age classification
    source: str = ""
    tags: tuple = ()              # e.g. ("classic", "restoration", "event")

    def as_dict(self):
        d = dataclasses.asdict(self)
        d["genres"] = list(self.genres)
        d["tags"] = list(self.tags)
        return d


def make_start(date: dt.date, hm) -> tuple[str, str, str]:
    h, m = hm
    return (
        f"{date.isoformat()}T{h:02d}:{m:02d}",
        date.isoformat(),
        f"{h:02d}:{m:02d}",
    )
