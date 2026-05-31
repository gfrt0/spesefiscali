"""Export measures table to JSON for the static web UI."""
from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path

from normattiva import annotate
from tributi import normalize as normalize_tributo
from governi import lookup as lookup_governo

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "db" / "spesefiscali.db"
WEB = ROOT / "web"
CLEAN_CSV = ROOT / "data" / "processed" / "descrizioni_clean.csv"


def load_cleaned_descrizioni() -> dict[int, str]:
    if not CLEAN_CSV.exists():
        return {}
    with CLEAN_CSV.open(encoding="utf-8") as f:
        return {int(r["n"]): r["descrizione_clean"] for r in csv.DictReader(f)}

COLS_FOR_UI = [
    "n", "missione", "norma", "descrizione", "tributo",
    "termine_vigenza", "natura",
    "effetto_t0 AS effetto_y0",
    "effetto_t1 AS effetto_y1",
    "effetto_t2 AS effetto_y2",
    "effetto_t0_raw AS effetto_y0_raw",
    "numero_frequenze", "effetto_procapite", "beneficiari",
    "vigore_5plus", "page",
]


def export_year(con, year: int, cleaned: dict[int, str]) -> tuple[int, int]:
    """Write web/measures_{year}.json and return (n_rows, n_resolved_urls)."""
    sql = (
        f"SELECT {', '.join(COLS_FOR_UI)} FROM measures "
        f"WHERE rsf_year={year} ORDER BY n"
    )
    rows = []
    resolved = 0
    for r in con.execute(sql):
        d = dict(r)
        d["rsf_year"] = year
        d.update(annotate(d["norma"] or ""))
        d.update(normalize_tributo(d["tributo"] or ""))
        d.update(lookup_governo(d.get("norma_data")))
        u = lookup_governo(d.get("norma_ultimo_data"))
        d["governo_ultimo"]    = u["governo"]
        d["coalizione_ultima"] = u["coalizione"]
        # Gemini cleanup currently only covers 2024.
        if year == 2024 and d["n"] in cleaned:
            d["descrizione_raw"] = d["descrizione"]
            d["descrizione"] = cleaned[d["n"]]
        if d["norma_url"]:
            resolved += 1
        rows.append(d)
    out = WEB / f"measures_{year}.json"
    out.write_text(json.dumps(rows, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return len(rows), resolved


def main():
    WEB.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    cleaned = load_cleaned_descrizioni()

    years = [y for (y,) in con.execute("SELECT DISTINCT rsf_year FROM measures ORDER BY rsf_year")]
    summary = []
    for y in years:
        n_rows, n_url = export_year(con, y, cleaned)
        size_kb = (WEB / f"measures_{y}.json").stat().st_size / 1024
        summary.append((y, n_rows, n_url, size_kb))
        print(f"  {y}: {n_rows} rows, {n_url} Normattiva URLs ({100*n_url/n_rows:.0f}%), {size_kb:.0f} KB")

    # Back-compat alias used by older deploys: measures.json -> latest year
    latest = max(years)
    alias = WEB / "measures.json"
    alias.write_bytes((WEB / f"measures_{latest}.json").read_bytes())
    print(f"  measures.json -> measures_{latest}.json (alias)")

    # Compact index for the year selector
    (WEB / "years.json").write_text(json.dumps({
        "years": years,
        "default": latest,
        "rows_by_year": {y: n for y, n, *_ in summary},
        "cleaned_descrizioni_years": [2024] if cleaned else [],
    }, ensure_ascii=False), encoding="utf-8")
    print(f"  years.json -> {years}")


if __name__ == "__main__":
    main()
