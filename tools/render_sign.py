#!/usr/bin/env python3
"""
Render the Vok Baths sign FROM a GitHub Action (not from the InTouch PC).

While Vok's own outdoor air sensor (202_HN02_STV) is out of order, the air
temperature is taken from HEF's public Tjarnarbraut weather page. This script
runs on GitHub's runners, so the InTouch PC never has to reach hef.is.

Inputs  (in the repo this runs in):
    lake.json   - published by the InTouch bridge; we use lake_c + measured_at.
Outputs (written into the repo; the workflow commits them):
    sign.html   - the baked, guest-facing sign (point LoopSign at this file).
    air.json    - the HEF air reading, for debugging and last-known-good.

Pure standard library; runs on the ubuntu-latest runner's python3.

NOTE: the HTML template below mirrors render.py in the bridge. While on this
HEF-via-Action setup, sign.html (made here) is the live sign; the bridge's own
index.html is unused. If you restyle the sign, change it here.
"""

import datetime
import json
import os
import re
import ssl
import string
import sys
import urllib.error
import urllib.request

LAKE_JSON = os.environ.get("LAKE_JSON", "lake.json")
SIGN_HTML = os.environ.get("SIGN_HTML", "sign.html")
AIR_JSON = os.environ.get("AIR_JSON", "air.json")
HEF_URL = os.environ.get("HEF_URL", "https://www.hef.is/is/eftirlitskerfi-hef/mqtt")

AIR_MIN = float(os.environ.get("AIR_MIN", "-30"))
AIR_MAX = float(os.environ.get("AIR_MAX", "30"))
MAX_LAKE_AGE_HOURS = float(os.environ.get("MAX_LAKE_AGE_HOURS", "6"))
HEF_TIMEOUT = float(os.environ.get("HEF_TIMEOUT_SECONDS", "15"))

# --- HEF scraping (mirror of hef_source.py) -------------------------------
_ANCHOR = re.compile(r"Tjarnarbraut\s+Egilsstaðir", re.IGNORECASE)
_HITASTIG = re.compile(
    r"Hitastig:\s*</td>\s*<td>\s*(-?\d{1,3}(?:[.,]\d+)?)", re.IGNORECASE)
_HITASTIG_LOOSE = re.compile(r"Hitastig:.*?(-?\d{1,3}[.,]\d+)",
                             re.IGNORECASE | re.DOTALL)


def fetch_hef_air():
    req = urllib.request.Request(HEF_URL, headers={"User-Agent": "vok-lake-bridge"})
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=HEF_TIMEOUT, context=ctx) as resp:
        if resp.status != 200:
            raise ValueError(f"HEF HTTP {resp.status}")
        html = resp.read().decode("utf-8", "replace")
    m = _ANCHOR.search(html)
    if not m:
        raise ValueError("Tjarnarbraut Egilsstadir row not found")
    seg = html[m.end():m.end() + 800]
    hit = _HITASTIG.search(seg) or _HITASTIG_LOOSE.search(seg)
    if not hit:
        raise ValueError("Hitastig value not found")
    return float(hit.group(1).replace(",", "."))


# --- rendering (mirror of render.py) --------------------------------------
def iso_z(dt):
    return dt.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s):
    try:
        return datetime.datetime.strptime(
            s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
    except Exception:
        return None


def _fmt_ice(v):
    return f"{v:.1f}".replace(".", ",")


def _fmt_clock(dt):
    return dt.astimezone(datetime.timezone.utc).strftime("%d.%m.%Y %H:%M")


_HTML = string.Template("""<!doctype html>
<html lang="is">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="900">
<title>Vatnshiti – Vök Baths</title>
<style>
  :root { color-scheme: light dark; }
  html, body { margin: 0; padding: 0; height: 100%; background: transparent; }
  body {
    font-family: "Segoe UI", "Helvetica Neue", Arial, system-ui, sans-serif;
    color: #ffffff; -webkit-font-smoothing: antialiased;
    text-shadow: 0 2px 12px rgba(0,0,0,0.55);
    display: flex; align-items: center; justify-content: center; min-height: 100vh;
  }
  .board { text-align: center; padding: 3vmin 5vmin; width: 100%; box-sizing: border-box; }
  .row { margin: 1.2vmin 0; }
  .label { font-size: clamp(18px, 3.4vmin, 46px); font-weight: 600; letter-spacing: 0.01em; opacity: 0.92; }
  .label .en { opacity: 0.7; font-weight: 400; }
  .value { font-weight: 800; line-height: 1.0; font-variant-numeric: tabular-nums; }
  .lake .value { font-size: clamp(80px, 24vmin, 360px); }
  .air  .value { font-size: clamp(46px, 12vmin, 180px); }
  .unit { font-weight: 600; opacity: 0.85; }
  .air  { margin-top: 3vmin; opacity: 0.95; }
  .stamp { margin-top: 4vmin; font-size: clamp(13px, 1.9vmin, 26px); opacity: 0.62; font-weight: 400; }
  .stale-note { display: ${stale_display}; margin-top: 0.6vmin; font-size: clamp(12px, 1.6vmin, 22px); opacity: 0.55; }
</style>
</head>
<body>
  <div class="board">
    <div class="row lake">
      <div class="label">Vatnshiti í Urriðavatni <span class="en">/ Lake temperature</span></div>
      <div class="value">${lake}<span class="unit"> &deg;C</span></div>
    </div>
    <div class="row air">
      <div class="label">Lofthiti <span class="en">/ Air</span></div>
      <div class="value">${air}<span class="unit"> &deg;C</span></div>
    </div>
    <div class="stamp">Mælt / Measured: ${measured}</div>
    <div class="stale-note">Síðasta staðfesta mæling / last confirmed reading</div>
  </div>
</body>
</html>
""")


def build_html(lake_c, air_c, measured_at, stale):
    return _HTML.substitute(
        lake=_fmt_ice(lake_c), air=_fmt_ice(air_c),
        measured=_fmt_clock(measured_at),
        stale_display="block" if stale else "none",
    ).encode("utf-8")


def main():
    now = datetime.datetime.now(datetime.timezone.utc)

    # Lake comes from the InTouch bridge via lake.json. Without it there is
    # nothing to show, so leave the sign untouched rather than blank the lake.
    if not os.path.exists(LAKE_JSON):
        print(f"{LAKE_JSON} not present yet; nothing to render.")
        return 0
    try:
        lake = json.load(open(LAKE_JSON, "r", encoding="utf-8"))
    except Exception as exc:
        print(f"could not read {LAKE_JSON}: {exc}")
        return 0
    lake_c = lake.get("lake_c")
    if lake_c is None:
        print("lake.json has no lake_c; leaving sign unchanged.")
        return 0
    measured = parse_iso(lake.get("measured_at")) or now
    lake_stale = (now - measured).total_seconds() / 3600.0 > MAX_LAKE_AGE_HOURS

    # Previous HEF air = last-known-good for the fallback.
    prev_air = None
    if os.path.exists(AIR_JSON):
        try:
            prev_air = json.load(open(AIR_JSON, "r", encoding="utf-8")).get("air_c")
        except Exception:
            pass

    air_ok = True
    reason = None
    try:
        air_c = fetch_hef_air()
        if not (AIR_MIN <= air_c <= AIR_MAX):
            raise ValueError(f"air {air_c} out of range [{AIR_MIN},{AIR_MAX}]")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        air_ok = False
        reason = str(exc)
        air_c = prev_air
        print(f"HEF air fetch failed ({reason}); using last-known-good {air_c}")

    stale = lake_stale or not air_ok
    if air_c is None:
        air_c = 0.0
        stale = True

    sign = build_html(lake_c, air_c, measured, stale)
    air_payload = (json.dumps({
        "air_c": round(air_c, 1),
        "source": "hef:tjarnarbraut",
        "ok": air_ok,
        "reason": reason,
        "fetched_at": iso_z(now),
    }, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")

    with open(SIGN_HTML, "wb") as fh:
        fh.write(sign)
    with open(AIR_JSON, "wb") as fh:
        fh.write(air_payload)

    print(f"rendered {SIGN_HTML}: lake={lake_c:.1f} air={air_c:.1f} "
          f"measured={iso_z(measured)} stale={stale} air_ok={air_ok}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
