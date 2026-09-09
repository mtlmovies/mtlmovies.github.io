"""Render data/status.json as a GitHub Actions step summary (Markdown)."""

import json
import os
import sys

path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "data", "status.json")

print("### Refresh summary\n")
try:
    with open(path, encoding="utf-8") as f:
        s = json.load(f)
except Exception as e:  # noqa: BLE001
    print(f"No `data/status.json` could be read ({e}) — the build failed.")
    sys.exit(0)

c = s.get("counts", {})
if c:
    print(f"**{c.get('movies','?')} films · {c.get('showtimes','?')} séances · "
          f"{c.get('venues','?')} cinémas**\n")
print(f"Generated at `{s.get('generated_at','?')}`\n")

print("| Source | Status | Screenings | Venues | Seconds |")
print("|---|---|---:|---:|---:|")
for r in s.get("sources", []):
    ok = r.get("ok")
    icon = "✅ ok" if ok else "⚠️ failed"
    err = "" if ok else f"<br>`{str(r.get('error',''))[:150]}`"
    print(f"| `{r.get('source','?')}` | {icon}{err} | {r.get('screenings',0)} | "
          f"{r.get('venues',0)} | {r.get('seconds','')} |")

failed = [r for r in s.get("sources", []) if not r.get("ok")]
if failed:
    print(f"\n> {len(failed)} source(s) unavailable this run. The site still "
          f"publishes everything that succeeded.")
