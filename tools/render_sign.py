#!/usr/bin/env python3
"""
Render sign.html = the bridge's own index.html, with ONLY the outdoor-air value
replaced by HEF's Tjarnarbraut reading.

While Vok's air sensor (202_HN02_STV) is dead, index.html (published hourly by
the InTouch bridge) shows a bogus outside temperature. This script, run by a
GitHub Action on GitHub's servers, takes that same index.html and swaps just the
air number for the live HEF value, writing sign.html. LoopSign points at
sign.html.

Why patch index.html instead of using our own template: the bridge owns the
sign's design. Starting from whatever index.html it last published means
sign.html always matches the current look automatically -- restyle index.html
and the sign follows -- and the only thing a guest sees changed is a correct
outdoor temperature instead of the dead sensor's value.

Pure standard library; runs on the ubuntu-latest runner's python3.
"""

import datetime
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.request

INDEX_HTML = os.environ.get("INDEX_HTML", "index.html")
SIGN_HTML = os.environ.get("SIGN_HTML", "sign.html")
AIR_JSON = os.environ.get("AIR_JSON", "air.json")
HEF_URL = os.environ.get("HEF_URL", "https://www.hef.is/is/eftirlitskerfi-hef/mqtt")

AIR_MIN = float(os.environ.get("AIR_MIN", "-30"))
AIR_MAX = float(os.environ.get("AIR_MAX", "30"))
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


# The outside-temperature number sits in <div class="value air">NN,N<span ...>.
# We replace only that text node, so the whole design is preserved untouched.
_AIR_SLOT = re.compile(r'(<div class="value air">)([^<]*)(<)')


def _fmt_ice(v):
    return f"{v:.1f}".replace(".", ",")


def main():
    now = datetime.datetime.now(datetime.timezone.utc)

    if not os.path.exists(INDEX_HTML):
        print(f"{INDEX_HTML} not present yet; nothing to render.")
        return 0
    html = open(INDEX_HTML, "r", encoding="utf-8").read()
    if not _AIR_SLOT.search(html):
        print("could not find the air value slot in index.html "
              "(<div class=\"value air\">); leaving sign unchanged.")
        return 0

    # Last-known-good air from the previous run, for the HEF-failure fallback.
    prev_air = None
    if os.path.exists(AIR_JSON):
        try:
            prev_air = json.load(open(AIR_JSON, "r", encoding="utf-8")).get("air_c")
        except Exception:
            pass

    ok = True
    reason = None
    try:
        air = fetch_hef_air()
        if not (AIR_MIN <= air <= AIR_MAX):
            raise ValueError(f"air {air} out of range [{AIR_MIN},{AIR_MAX}]")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        ok = False
        reason = str(exc)
        air = prev_air
        print(f"HEF fetch failed ({reason}); using last-known-good {air}")

    if air is None:
        print("no HEF air and no last-known-good; leaving sign unchanged.")
        return 0

    sign = _AIR_SLOT.sub(lambda m: m.group(1) + _fmt_ice(air) + m.group(3),
                         html, count=1)
    if not ok:
        # Reveal the "last confirmed reading" stamp if the design hides it.
        sign = sign.replace("    display: none;", "    display: block;", 1)

    with open(SIGN_HTML, "w", encoding="utf-8") as fh:
        fh.write(sign)
    with open(AIR_JSON, "w", encoding="utf-8") as fh:
        json.dump({
            "air_c": round(air, 1),
            "source": "hef:tjarnarbraut",
            "ok": ok,
            "reason": reason,
            "fetched_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")

    print(f"rendered {SIGN_HTML}: air={_fmt_ice(air)} (ok={ok}) "
          f"from {INDEX_HTML}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
