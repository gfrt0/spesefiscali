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
OUT = ROOT / "web" / "measures.json"
OUT_PANEL = ROOT / "web" / "panel.json"
CLEAN_CSV = ROOT / "data" / "processed" / "descrizioni_clean.csv"


def load_cleaned_descrizioni() -> dict[int, str]:
    if not CLEAN_CSV.exists():
        return {}
    with CLEAN_CSV.open(encoding="utf-8") as f:
        return {int(r["n"]): r["descrizione_clean"] for r in csv.DictReader(f)}

COLS_FOR_UI = [
    "n", "missione", "norma", "descrizione", "tributo",
    "termine_vigenza", "natura",
    "effetto_t0 AS effetto_2025",
    "effetto_t1 AS effetto_2026",
    "effetto_t2 AS effetto_2027",
    "effetto_t0_raw AS effetto_2025_raw",
    "numero_frequenze", "effetto_procapite", "beneficiari",
    "vigore_5plus", "page",
]


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    cleaned = load_cleaned_descrizioni()
    rows = []
    resolved = 0
    sql = f"SELECT {', '.join(COLS_FOR_UI)} FROM measures WHERE rsf_year=2024 ORDER BY n"
    for r in con.execute(sql):
        d = dict(r)
        d.update(annotate(d["norma"] or ""))
        d.update(normalize_tributo(d["tributo"] or ""))
        d.update(lookup_governo(d.get("norma_data")))
        u = lookup_governo(d.get("norma_ultimo_data"))
        d["governo_ultimo"]    = u["governo"]
        d["coalizione_ultima"] = u["coalizione"]
        if d["n"] in cleaned:
            d["descrizione_raw"] = d["descrizione"]
            d["descrizione"] = cleaned[d["n"]]
        if d["norma_url"]:
            resolved += 1
        rows.append(d)
    OUT.write_text(json.dumps(rows, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {len(rows)} rows -> {OUT} ({OUT.stat().st_size/1024:.0f} KB)")
    print(f"Normattiva URLs resolved: {resolved}/{len(rows)} ({100*resolved/len(rows):.1f}%)")
    if cleaned:
        print(f"Descrizioni cleaned (Gemini-pass): {len(cleaned)}/{len(rows)}")

    # Compact panel JSON: minimal columns for cross-edition charts.
    panel_sql = """
      SELECT rsf_year, n, measure_uid, missione, tributo, natura,
             effetto_t0, effetto_t1, effetto_t2
      FROM measures
      WHERE measure_uid IS NOT NULL
      ORDER BY measure_uid, rsf_year
    """
    panel = [dict(r) for r in con.execute(panel_sql)]
    OUT_PANEL.write_text(json.dumps(panel, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    n_uids = len({r["measure_uid"] for r in panel})
    print(f"wrote {len(panel)} panel rows ({n_uids} UIDs) -> {OUT_PANEL} ({OUT_PANEL.stat().st_size/1024:.0f} KB)")


if __name__ == "__main__":
    main()
