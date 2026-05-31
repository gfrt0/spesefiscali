"""Load every parsed RSF edition into a single SQLite panel.

Each row is keyed on (rsf_year, n). Financial effects are stored as
generic t0/t1/t2 columns (forecasts for rsf_year+1, +2, +3 respectively)
because the calendar-year triplet shifts edition by edition. A
`measures_long` view unpivots them for calendar-year queries.

A best-effort cross-edition `measure_uid` is derived from
(tipo_atto, anno_atto, numero_atto, articolo) of the norma istitutiva
(URN without the comma anchor). Rows without a parsed URN keep
measure_uid = NULL.
"""
from __future__ import annotations

import csv
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROCESSED = ROOT / "data" / "processed"
DB = ROOT / "db" / "spesefiscali.db"

sys.path.insert(0, str(ROOT / "src"))
from normattiva import parse_norma, TIPO_ATTO_MAP, _norm_tipo  # noqa: E402

# Fallback pattern for abbreviated cites common in RSF 2016-2021, e.g.:
#   "D.P.R. n. 633/72", "Legge 604/1954", "L. 178/2020",
#   "art. 1, comma 908 della legge 28/12/2015 n. 208"   -> already by main parser
# The pattern is <TIPO> [n.] <num>/<yy or yyyy>.
_TIPO_ALT = r"(d\.?\s*lgs\.?|decreto\s+legislativo|d\.?\s*l\.?(?!\s*g)|" \
            r"decreto[-\s]+legge|d\.?\s*p\.?\s*r\.?|d\.?\s*m\.?|r\.?\s*d\.?|legge|l\.)"
CITE_SHORT = re.compile(
    rf"\b{_TIPO_ALT}\s*(?:n\.\s*)?(?P<num>\d{{1,5}})\s*/\s*(?P<yy>\d{{2,4}})\b",
    re.IGNORECASE,
)
# "D.L. n. 34 del 2019" / "legge n. 116 del 1995" / "D.lgs. N. 347 del 1990"
CITE_DEL = re.compile(
    rf"\b{_TIPO_ALT}\s*(?:n\.\s*)?(?P<num>\d{{1,5}})\s+del\s+(?P<yy>\d{{4}})\b",
    re.IGNORECASE,
)

# Article anchor (same shape as normattiva.ART_RE)
ART_ANCHOR = re.compile(
    r"\bart(?:\.|icolo)?\s*(?P<art>\d+(?:[\-\s]?(?:bis|ter|quater|quinquies|sexies|septies|octies|novies|decies))?)",
    re.IGNORECASE,
)

SCHEMA = """
DROP VIEW  IF EXISTS measures_long;
DROP TABLE IF EXISTS measures_fts;
DROP TABLE IF EXISTS measures;

CREATE TABLE measures (
    id              INTEGER PRIMARY KEY,
    rsf_year        INTEGER NOT NULL,
    n               INTEGER NOT NULL,
    measure_uid     TEXT,
    missione        TEXT,
    norma           TEXT,
    descrizione     TEXT,
    tributo         TEXT,
    termine_vigenza TEXT,
    natura          TEXT,
    effetto_t0      REAL, effetto_t1 REAL, effetto_t2 REAL,
    effetto_t0_raw  TEXT, effetto_t1_raw TEXT, effetto_t2_raw TEXT,
    numero_frequenze  TEXT,
    effetto_procapite TEXT,
    beneficiari       TEXT,
    vigore_5plus      TEXT,
    page              INTEGER,
    UNIQUE(rsf_year, n)
);
CREATE INDEX idx_measures_year       ON measures(rsf_year);
CREATE INDEX idx_measures_uid        ON measures(measure_uid);
CREATE INDEX idx_measures_missione   ON measures(missione);
CREATE INDEX idx_measures_tributo    ON measures(tributo);
CREATE INDEX idx_measures_natura     ON measures(natura);

CREATE VIEW measures_long AS
  SELECT id, rsf_year, n, measure_uid, rsf_year+1 AS forecast_year, effetto_t0 AS effetto FROM measures
  UNION ALL
  SELECT id, rsf_year, n, measure_uid, rsf_year+2,             effetto_t1            FROM measures
  UNION ALL
  SELECT id, rsf_year, n, measure_uid, rsf_year+3,             effetto_t2            FROM measures;

CREATE VIRTUAL TABLE measures_fts USING fts5(
    descrizione, norma, beneficiari, missione,
    content='measures', content_rowid='id'
);
"""

FTS_REBUILD = """
INSERT INTO measures_fts(rowid, descrizione, norma, beneficiari, missione)
    SELECT id, descrizione, norma, beneficiari, missione FROM measures;
"""


def parse_eur(s: str) -> float | None:
    if not s:
        return None
    t = s.strip()
    if not t or t.lower().startswith("non quantif"):
        return None
    t = t.replace(" ", "")
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def _norm_tipo_alt(s: str) -> str | None:
    t = re.sub(r"\s+", "", s.lower()).rstrip(".")
    for pat, canon in TIPO_ATTO_MAP:
        if re.fullmatch(pat.replace(r"\s*", ""), t):
            return canon
    return _norm_tipo(s)


def _norm_anno(yy: str) -> str:
    return yy if len(yy) == 4 else ("19" + yy if int(yy) >= 30 else "20" + yy)


def _tok(s: str | None) -> str:
    if not s:
        return ""
    return re.sub(r"\s+", "", s.lower()).replace("-", "").replace(".", "")


# Capture the full anchor sequence after the article in the source string:
# "Art. 15, comma 1, lett. a)" -> "com1-letta"
# "Art. 1, comma 583, lett. b)" -> "com583-lettb"
# "Tabella A, punto 5"         -> "punto5"
ANCHOR_TAIL = re.compile(
    r"(?:,\s*)?"
    r"(?:comma\s+(?P<com>[\dA-Za-z\-.]+))?"
    r"(?:[,\s]+lett(?:era|\.)\s*(?P<lett>[\dA-Za-z\-]+)\)?)?"
    r"(?:[,\s]+(?:punto\s+(?P<punto>[\dA-Za-z\-]+)|"
    r"numero\s+(?P<num>[\dA-Za-z\-]+)|"
    r"n\.\s*(?P<num2>[\dA-Za-z\-]+)))?",
    re.IGNORECASE,
)


def _anchor_after(s: str, art_end: int) -> str:
    m = ANCHOR_TAIL.match(s[art_end:])
    if not m:
        return ""
    parts = []
    if m.group("com"):   parts.append(f"com{_tok(m.group('com'))}")
    if m.group("lett"):  parts.append(f"lett{_tok(m.group('lett'))}")
    if m.group("punto"): parts.append(f"punto{_tok(m.group('punto'))}")
    n2 = m.group("num") or m.group("num2")
    if n2: parts.append(f"n{_tok(n2)}")
    return "-".join(parts)


def _suffix(art: str, anchor: str) -> str:
    if not art:
        return ""
    out = f"~art{art}"
    if anchor:
        out += f"-{anchor}"
    return out


def make_uid(norma: str) -> str | None:
    """Stable cross-edition key from the norma istitutiva.

    Form: '<tipo>:<YYYY>;<numero>[~art<N>[-com<M>]]'.

    Year-level granularity on the date so that day/month variants match.
    Comma included when available -- crucial for laws with many articulated
    measures under the same article (e.g. TUIR Art.15 contains dozens of
    distinct detrazioni distinguished only by comma+lettera).
    """
    p = parse_norma(norma or "")
    if p.tipo and p.data and p.numero:
        anno = p.data[:4]
        art = _tok(p.articolo)
        # Walk the original string for the full anchor (comma + lett + ...)
        anchor = ""
        if art:
            art_m = ART_ANCHOR.search(norma or "")
            if art_m:
                anchor = _anchor_after(norma, art_m.end())
        return f"{p.tipo}:{anno};{p.numero}" + _suffix(art, anchor)
    # Fallback: abbreviated cite
    m = CITE_SHORT.search(norma or "") or CITE_DEL.search(norma or "")
    if not m:
        return None
    tipo = _norm_tipo_alt(m.group(1))
    if not tipo:
        return None
    anno = _norm_anno(m.group("yy"))
    art_m = ART_ANCHOR.search(norma or "")
    art = _tok(art_m.group("art")) if art_m else ""
    anchor = _anchor_after(norma, art_m.end()) if art_m else ""
    return f"{tipo}:{anno};{m.group('num')}" + _suffix(art, anchor)


def find_csvs() -> list[Path]:
    return sorted(PROCESSED.glob("measures_[0-9][0-9][0-9][0-9].csv"))


def main():
    DB.parent.mkdir(parents=True, exist_ok=True)
    if DB.exists():
        DB.unlink()
    con = sqlite3.connect(DB)
    con.executescript(SCHEMA)

    rows = []
    rid = 0
    for path in find_csvs():
        year = int(path.stem.split("_")[1])
        with path.open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                rid += 1
                rows.append((
                    rid, year, int(r["n"]),
                    make_uid(r["norma"]),
                    r["missione"], r["norma"], r["descrizione"], r["tributo"],
                    r["termine_vigenza"], r["natura"],
                    parse_eur(r["effetto_2025"]),  # t0 = rsf_year+1
                    parse_eur(r["effetto_2026"]),  # t1
                    parse_eur(r["effetto_2027"]),  # t2
                    r["effetto_2025"], r["effetto_2026"], r["effetto_2027"],
                    r["numero_frequenze"], r["effetto_procapite"],
                    r["beneficiari"], r["vigore_5plus"],
                    int(r["page"]) if r.get("page") else None,
                ))
    con.executemany(
        "INSERT INTO measures VALUES (" + ",".join("?" * 21) + ")",
        rows,
    )
    con.executescript(FTS_REBUILD)
    con.commit()

    print(f"loaded {rid} rows from {len(find_csvs())} editions into {DB}")
    print(f"\nPer-year row counts:")
    for y, n in con.execute(
        "SELECT rsf_year, COUNT(*) FROM measures GROUP BY rsf_year ORDER BY rsf_year"
    ):
        print(f"  {y}: {n}")
    print(f"\nMeasure UID coverage:")
    matched = con.execute("SELECT COUNT(*) FROM measures WHERE measure_uid IS NOT NULL").fetchone()[0]
    print(f"  {matched}/{rid} rows have a measure_uid ({100*matched/rid:.1f}%)")
    distinct = con.execute("SELECT COUNT(DISTINCT measure_uid) FROM measures WHERE measure_uid IS NOT NULL").fetchone()[0]
    print(f"  {distinct} distinct UIDs (avg {matched/distinct:.1f} appearances each)")
    multi_year = con.execute("""
        SELECT COUNT(*) FROM (
            SELECT measure_uid FROM measures
            WHERE measure_uid IS NOT NULL
            GROUP BY measure_uid HAVING COUNT(DISTINCT rsf_year) > 1
        )
    """).fetchone()[0]
    print(f"  {multi_year} UIDs appear in >1 edition (the actual panel)")
    con.close()


if __name__ == "__main__":
    main()
