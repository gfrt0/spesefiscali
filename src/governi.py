"""Map a date to the Italian government in office on that date.

Coverage: all post-war Italian governments. Each entry is the start date
(inauguration / fiducia) of a new executive; the previous government's end
date is the next entry's start date minus one day.

For a measure with parsed `norma_data`, this gives the executive that
introduced it — which is usually the more interesting political-economy
attribution than the per-vote roll-call (most fiscal measures are passed
in maxi-emendamenti to the Legge di Bilancio voted under fiducia).

Source: Camera dei Deputati, "Governi italiani".
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Governo:
    nome: str
    coalizione: str   # short, ASCII tag used for coloring
    inizio: date


GOVERNI: list[Governo] = [
    # --- I Repubblica, sintetica fino al 1970 ---
    Governo("Pre-Repubblica",  "altro",         date(1900, 1, 1)),
    Governo("I Repubblica",    "dc-pentapartito", date(1948, 5, 23)),
    # --- Da Colombo in poi, governi singoli ---
    Governo("Colombo",         "dc-pentapartito", date(1970, 8,  6)),
    Governo("Andreotti II",    "dc-pentapartito", date(1972, 2, 17)),
    Governo("Andreotti III",   "dc-pentapartito", date(1976, 7, 29)),
    Governo("Andreotti IV",    "dc-pentapartito", date(1978, 3, 11)),
    Governo("Andreotti V",     "dc-pentapartito", date(1979, 3, 20)),
    Governo("Cossiga I",       "dc-pentapartito", date(1979, 8,  4)),
    Governo("Cossiga II",      "dc-pentapartito", date(1980, 4,  4)),
    Governo("Forlani",         "dc-pentapartito", date(1980,10, 18)),
    Governo("Spadolini I",     "dc-pentapartito", date(1981, 6, 28)),
    Governo("Spadolini II",    "dc-pentapartito", date(1982, 8, 23)),
    Governo("Fanfani V",       "dc-pentapartito", date(1982,12,  1)),
    Governo("Craxi I",         "dc-pentapartito", date(1983, 8,  4)),
    Governo("Craxi II",        "dc-pentapartito", date(1986, 8,  1)),
    Governo("Fanfani VI",      "dc-pentapartito", date(1987, 4, 17)),
    Governo("Goria",           "dc-pentapartito", date(1987, 7, 28)),
    Governo("De Mita",         "dc-pentapartito", date(1988, 4, 13)),
    Governo("Andreotti VI",    "dc-pentapartito", date(1989, 7, 22)),
    Governo("Andreotti VII",   "dc-pentapartito", date(1991, 4, 12)),
    Governo("Amato I",         "dc-pentapartito", date(1992, 6, 28)),
    Governo("Ciampi",          "tecnico",         date(1993, 4, 28)),
    Governo("Berlusconi I",    "centrodestra",    date(1994, 5, 10)),
    Governo("Dini",            "tecnico",         date(1995, 1, 17)),
    Governo("Prodi I",         "centrosinistra",  date(1996, 5, 17)),
    Governo("D'Alema I",       "centrosinistra",  date(1998,10, 21)),
    Governo("D'Alema II",      "centrosinistra",  date(1999,12, 22)),
    Governo("Amato II",        "centrosinistra",  date(2000, 4, 25)),
    Governo("Berlusconi II",   "centrodestra",    date(2001, 6, 11)),
    Governo("Berlusconi III",  "centrodestra",    date(2005, 4, 23)),
    Governo("Prodi II",        "centrosinistra",  date(2006, 5, 17)),
    Governo("Berlusconi IV",   "centrodestra",    date(2008, 5,  8)),
    Governo("Monti",           "tecnico",         date(2011,11, 16)),
    Governo("Letta",           "larghe-intese",   date(2013, 4, 28)),
    Governo("Renzi",           "centrosinistra",  date(2014, 2, 22)),
    Governo("Gentiloni",       "centrosinistra",  date(2016,12, 12)),
    Governo("Conte I",         "giallo-verde",    date(2018, 6,  1)),
    Governo("Conte II",        "giallo-rosso",    date(2019, 9,  5)),
    Governo("Draghi",          "unita-nazionale", date(2021, 2, 13)),
    Governo("Meloni",          "centrodestra",    date(2022,10, 22)),
]

_INDEX = [g.inizio for g in GOVERNI]


def lookup(data_iso: str | None) -> dict:
    """Given a 'YYYY-MM-DD' string, return the governo in office on that date."""
    if not data_iso:
        return {"governo": None, "coalizione": None}
    try:
        d = date.fromisoformat(data_iso)
    except ValueError:
        return {"governo": None, "coalizione": None}
    idx = bisect_right(_INDEX, d) - 1
    if idx < 0:
        return {"governo": None, "coalizione": None}
    g = GOVERNI[idx]
    return {"governo": g.nome, "coalizione": g.coalizione}


if __name__ == "__main__":
    import sqlite3
    from pathlib import Path
    from collections import Counter
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from normattiva import parse_norma
    con = sqlite3.connect(Path(__file__).resolve().parent.parent / "db" / "spesefiscali.db")
    c = Counter()
    for (norma,) in con.execute("SELECT norma FROM measures"):
        p = parse_norma(norma or "")
        g = lookup(p.data)["governo"]
        c[g] += 1
    print("Misure per governo istitutore (top):")
    for g, n in c.most_common(20):
        print(f"  {n:>4d}  {g}")
