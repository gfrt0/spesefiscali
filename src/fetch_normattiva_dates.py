"""Resolve year-only Normattiva URNs to their actual publication date.

The RSF 2016-2021 editions cite many laws in abbreviated form ('L.
178/2020', 'D.L. n. 34 del 2019') with only the year. We build year-only
URNs from those (`urn:nir:stato:legge:2020;178`) -- Normattiva accepts
them -- but we lose day/month, which dents `governi.lookup` precision
for measures introduced near a change of cabinet.

This script fetches each distinct year-only URN once, parses the
`dataPubblicazioneGazzetta=YYYY-MM-DD` token out of the response HTML,
and caches the result in `data/processed/normattiva_dates.csv`.

Reruns are idempotent: only URNs missing from the cache are fetched.
"""
from __future__ import annotations

import csv
import re
import sqlite3
import sys
import time
import urllib.request
import urllib.parse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "db" / "spesefiscali.db"
CACHE = ROOT / "data" / "processed" / "normattiva_dates.csv"

DATE_RE = re.compile(rb"dataPubblicazioneGazzetta=(\d{4}-\d{2}-\d{2})")

# Be polite: small worker pool + per-request timeout.
WORKERS = 6
TIMEOUT = 20
SLEEP_BETWEEN = 0.05    # seconds; combined with concurrency keeps load light


def load_cache() -> dict[str, str]:
    if not CACHE.exists():
        return {}
    with CACHE.open(encoding="utf-8") as f:
        return {r["urn"]: r["data_pubblicazione"] for r in csv.DictReader(f)}


def save_cache(cache: dict[str, str]) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    with CACHE.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["urn", "data_pubblicazione"])
        for urn in sorted(cache):
            w.writerow([urn, cache[urn]])


def collect_year_only_urns(con) -> set[str]:
    """URNs in the DB that are year-only (no day/month in the date part)."""
    out: set[str] = set()
    sys.path.insert(0, str(ROOT / "src"))
    from normattiva import parse_norma     # noqa: E402
    for (norma,) in con.execute("SELECT DISTINCT norma FROM measures"):
        p = parse_norma(norma or "")
        if p.urn and p.data and len(p.data) == 4:   # year-only
            # Strip article anchor; we want the base URN
            base = p.urn.split("~", 1)[0]
            out.add(base)
    return out


def fetch_one(urn: str) -> tuple[str, str | None]:
    url = f"https://www.normattiva.it/uri-res/N2Ls?{urllib.parse.quote(urn, safe=':;')}!vig="
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "spesefiscali/0.1"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = resp.read()
        m = DATE_RE.search(data)
        return urn, (m.group(1).decode() if m else None)
    except Exception:
        return urn, None


def main():
    con = sqlite3.connect(DB)
    cache = load_cache()
    urns = collect_year_only_urns(con)
    todo = sorted(urns - set(cache))
    print(f"{len(urns)} distinct year-only URNs;  {len(cache)} cached;  {len(todo)} to fetch")
    if not todo:
        return

    found = 0
    started = time.time()
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = [ex.submit(fetch_one, u) for u in todo]
        for i, fut in enumerate(as_completed(futs), 1):
            urn, date = fut.result()
            if date:
                cache[urn] = date
                found += 1
            if i % 25 == 0 or i == len(futs):
                rate = i / max(time.time() - started, 1e-6)
                print(f"  {i}/{len(todo)}  ({rate:.1f}/s, {found} resolved)")
            time.sleep(SLEEP_BETWEEN)
    save_cache(cache)
    print(f"\nresolved {found}/{len(todo)} new URNs; total cache: {len(cache)}")
    if found < len(todo):
        misses = [u for u in todo if u not in cache]
        print(f"unresolved (first 10): {misses[:10]}")


if __name__ == "__main__":
    main()
