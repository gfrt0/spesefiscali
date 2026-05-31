"""Load parsed CSV into SQLite, add FTS index on descrizione+norma."""
from __future__ import annotations

import csv
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSV_IN = ROOT / "data" / "processed" / "measures_2024.csv"
DB = ROOT / "db" / "spesefiscali.db"

SCHEMA = """
DROP TABLE IF EXISTS measures;
CREATE TABLE measures (
    id              INTEGER PRIMARY KEY,
    rsf_year        INTEGER NOT NULL,
    n               INTEGER NOT NULL,
    missione        TEXT,
    norma           TEXT,
    descrizione     TEXT,
    tributo         TEXT,
    termine_vigenza TEXT,
    natura          TEXT,
    effetto_2025    REAL,
    effetto_2026    REAL,
    effetto_2027    REAL,
    effetto_2025_raw TEXT,
    effetto_2026_raw TEXT,
    effetto_2027_raw TEXT,
    numero_frequenze TEXT,
    effetto_procapite TEXT,
    beneficiari     TEXT,
    vigore_5plus    TEXT,
    page            INTEGER
);
CREATE INDEX idx_measures_missione ON measures(missione);
CREATE INDEX idx_measures_tributo  ON measures(tributo);
CREATE INDEX idx_measures_natura   ON measures(natura);
"""

FTS = """
DROP TABLE IF EXISTS measures_fts;
CREATE VIRTUAL TABLE measures_fts USING fts5(
    descrizione, norma, beneficiari, missione,
    content='measures', content_rowid='id'
);
INSERT INTO measures_fts(rowid, descrizione, norma, beneficiari, missione)
    SELECT id, descrizione, norma, beneficiari, missione FROM measures;
"""


def parse_eur(s: str) -> float | None:
    """RSF uses ',' as decimal separator and '.' as thousands; '-' prefix is a loss."""
    if not s:
        return None
    t = s.strip()
    if not t or t.lower().startswith("non quantif"):
        return None
    # strip currency clutter
    t = t.replace(" ", " ").replace(" ", "")
    # remove thousands separators ('.'), convert decimal ','
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def main():
    DB.parent.mkdir(parents=True, exist_ok=True)
    if DB.exists():
        DB.unlink()
    con = sqlite3.connect(DB)
    con.executescript(SCHEMA)
    with CSV_IN.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = []
        for i, r in enumerate(reader, start=1):
            rows.append((
                i,
                2024,
                int(r["n"]),
                r["missione"], r["norma"], r["descrizione"], r["tributo"],
                r["termine_vigenza"], r["natura"],
                parse_eur(r["effetto_2025"]),
                parse_eur(r["effetto_2026"]),
                parse_eur(r["effetto_2027"]),
                r["effetto_2025"], r["effetto_2026"], r["effetto_2027"],
                r["numero_frequenze"], r["effetto_procapite"],
                r["beneficiari"], r["vigore_5plus"],
                int(r["page"]) if r.get("page") else None,
            ))
    con.executemany(
        "INSERT INTO measures VALUES (" + ",".join("?" * 20) + ")",
        rows,
    )
    con.executescript(FTS)
    con.commit()
    n = con.execute("SELECT COUNT(*) FROM measures").fetchone()[0]
    total_2025 = con.execute("SELECT SUM(effetto_2025) FROM measures").fetchone()[0]
    print(f"loaded {n} measures into {DB}")
    print(f"sum effetto_2025 (quantified only): {total_2025:,.1f} mln EUR")
    con.close()


if __name__ == "__main__":
    main()
