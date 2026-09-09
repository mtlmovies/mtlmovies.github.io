"""Diagnostic: show what each source actually returns from THIS network.

Some venues (Cinéma Moderne, Cinémathèque, Théâtre Outremont) sit behind WAFs
that block certain networks at the TCP/TLS layer or with a 403. Run this from a
GitHub Actions runner to see what the scraper will really get:

    python3 scrapers/probe.py
"""

from __future__ import annotations

import socket
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

from common import BROWSER_UA, USER_AGENT

TARGETS = [
    "https://cinemacinema.ca/fr/cinema-du-parc/horaire/__data.json",
    "https://cinemamoderne.ticketacces.net/fr/organisation/index.cfm",
    "https://cinemapublic.ticketacces.net/fr/organisation/index.cfm",
    "https://www.cinemamoderne.com/en/schedule/2026/09/",
    "https://cinemapublic.ca/horaire/",
    "https://apis.cineplex.com/prod/cpx/theatrical/api/v1/theatres?language=en",
    "https://www.cinestarz.ca/movie-theater/cotedesneiges",
    "https://www.cinemasguzzo.com/cinemas.html",
    "https://www.cinematheque.qc.ca/fr/programme/",
    "https://www.cinematheque.qc.ca/fr/cinema/le-conformiste/",
    "https://theatreoutremont.ca/",
    "https://letterboxd.com/imdb/tt0033467/",
]


def tcp_tls(host: str) -> str:
    try:
        s = socket.create_connection((host, 443), timeout=8)
    except Exception as e:  # noqa: BLE001
        return f"TCP FAIL ({type(e).__name__}: {e})"
    try:
        c = ssl.create_default_context().wrap_socket(s, server_hostname=host)
        v = c.version()
        c.close()
        return f"TCP+TLS ok ({v})"
    except Exception as e:  # noqa: BLE001
        return f"TLS FAIL ({type(e).__name__}: {e})"
    finally:
        try:
            s.close()
        except Exception:
            pass


def probe(url: str, ua: str, label: str):
    req = urllib.request.Request(url, headers={
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
        "Accept-Language": "fr-CA,fr;q=0.9,en;q=0.8",
    })
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            body = r.read(1500)
            print(f"    {label:9s} {r.status}  {len(body)}+ bytes  ct={r.headers.get('Content-Type','?')[:40]}")
            return True
    except urllib.error.HTTPError as e:
        snippet = (e.read(200) or b"").decode("utf-8", "replace").replace("\n", " ")[:120]
        print(f"    {label:9s} HTTP {e.code}  {snippet}")
    except Exception as e:  # noqa: BLE001
        print(f"    {label:9s} ERROR {type(e).__name__}: {e}")
    return False


def main():
    print("=" * 78)
    print("Source reachability probe")
    print("=" * 78)
    for url in TARGETS:
        host = urllib.parse.urlparse(url).netloc
        print(f"\n{url}")
        print(f"    network   {tcp_tls(host)}")
        ok = probe(url, USER_AGENT, "polite")
        if not ok:
            probe(url, BROWSER_UA, "browser")
    print("\nDone.")


if __name__ == "__main__":
    sys.exit(main())
