"""Parse the raw `termine_vigenza` column into structured kind + terminal year.

RSF's "termine di vigenza" is free-text and noisy across editions, but
~97% of rows fall into a small grammar:

  - "A REGIME" (and miscapitalised/spaced variants)       -> open-ended
  - "A REGIME FINO A ..."                                 -> conditional
  - bare year(s):     "2020", "2020 e 2021", "2017-2019",
                      "2020/2021", "2019, 2020, 2021 e 2022"
  - dotted dates:     "30/06/2022", "31-dic-16",
                      "dal 01/07/2021 al 31/12/2021"
  - genuinely descriptive ("14 periodi d'imposta",
    "spettante per mutui contratti nel 1997")             -> altro

Outputs:
  vigenza_kind   "regime" | "terminal_year" | "conditional_regime" | "altro"
  vigenza_year   int (last applicable year) or None
  vigenza_label  short normalised display string
"""
from __future__ import annotations

import re
import unicodedata


def _strip(s: str) -> str:
    # NFKC normalise and squash whitespace; keep accents.
    s = unicodedata.normalize("NFKC", s or "").strip()
    s = re.sub(r"\s+", " ", s)
    return s


# "A REGIME" with tolerance for spacing typos ("a r e gime") and case
_REGIME_RE = re.compile(r"\b(?:a\s*)?r\s*e\s*g\s*i\s*m\s*e\b", re.IGNORECASE)
# 4-digit years between 1980 and 2099 — covers the RSF universe.
_YEAR_RE = re.compile(r"\b(19[89]\d|20\d{2})\b")
# Two-digit year suffixes in dotted dates, e.g. "31-dic-16"
_MESI_ABBR = {
    "gen": 1, "feb": 2, "mar": 3, "apr": 4, "mag": 5, "giu": 6,
    "lug": 7, "ago": 8, "set": 9, "ott": 10, "nov": 11, "dic": 12,
}
_DATE_DDMONYY = re.compile(
    rf"\b(\d{{1,2}})[-/\s]({'|'.join(_MESI_ABBR)})[-/\s](\d{{2,4}})\b",
    re.IGNORECASE,
)


def _years_in(s: str) -> list[int]:
    """All 4-digit years anywhere in the string, in order of appearance."""
    out = [int(m.group(1)) for m in _YEAR_RE.finditer(s)]
    # Also catch dd-mon-yy → convert to 4-digit year.
    for m in _DATE_DDMONYY.finditer(s):
        yy = int(m.group(3))
        if len(m.group(3)) == 2:
            yy = 2000 + yy if yy < 50 else 1900 + yy
        out.append(yy)
    return out


def normalize(raw: str) -> dict:
    s = _strip(raw)
    if not s:
        return {"vigenza_kind": None, "vigenza_year": None, "vigenza_label": ""}

    has_regime = bool(_REGIME_RE.search(s))
    low = s.lower()

    # "A REGIME FINO A..." (or "FINO ALL'..."): conditional regime.
    # Treat as regime-with-sunset only if the FINO clause is present alongside REGIME.
    if has_regime and re.search(r"\bfino\s+a", low):
        return {"vigenza_kind": "conditional_regime",
                "vigenza_year": None,
                "vigenza_label": "A regime (condizionato)"}

    # Plain regime.
    if has_regime:
        return {"vigenza_kind": "regime",
                "vigenza_year": None,
                "vigenza_label": "A regime"}

    # Year-based parse.
    years = _years_in(s)
    if years:
        terminal = max(years)
        years_sorted = sorted(set(years))
        if len(years_sorted) == 1:
            label = str(terminal)
        elif years_sorted == list(range(years_sorted[0], years_sorted[-1] + 1)):
            label = f"{years_sorted[0]}–{years_sorted[-1]}"
        else:
            label = ", ".join(str(y) for y in years_sorted)
        return {"vigenza_kind": "terminal_year",
                "vigenza_year": terminal,
                "vigenza_label": label}

    # Descriptive / unparseable -- keep the (cleaned-whitespace) original text
    # so the cell still shows what the RSF printed.
    return {"vigenza_kind": "altro",
            "vigenza_year": None,
            "vigenza_label": s}


if __name__ == "__main__":
    import sqlite3, collections
    from pathlib import Path
    DB = Path(__file__).resolve().parent.parent / "db" / "spesefiscali.db"
    con = sqlite3.connect(DB)
    rows = list(con.execute("SELECT termine_vigenza FROM measures"))
    kinds = collections.Counter()
    samples = collections.defaultdict(list)
    for (v,) in rows:
        r = normalize(v or "")
        kinds[r["vigenza_kind"]] += 1
        if len(samples[r["vigenza_kind"]]) < 5:
            samples[r["vigenza_kind"]].append((v, r))
    print(f"{len(rows)} rows; kinds:", dict(kinds))
    for k, exs in samples.items():
        print(f"\n--- {k} ---")
        for v, r in exs:
            print(f"  raw={v!r}\n   -> {r}")
