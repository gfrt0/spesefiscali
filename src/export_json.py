"""Export measures table to JSON for the static web UI."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from normattiva import annotate
from tributi import normalize as normalize_tributo

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "db" / "spesefiscali.db"
OUT = ROOT / "web" / "measures.json"

COLS = [
    "n", "missione", "norma", "descrizione", "tributo",
    "termine_vigenza", "natura",
    "effetto_2025", "effetto_2026", "effetto_2027",
    "effetto_2025_raw",
    "numero_frequenze", "effetto_procapite", "beneficiari",
    "vigore_5plus", "page",
]


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = []
    resolved = 0
    for r in con.execute(f"SELECT {', '.join(COLS)} FROM measures ORDER BY n"):
        d = dict(r)
        d.update(annotate(d["norma"] or ""))
        d.update(normalize_tributo(d["tributo"] or ""))
        if d["norma_url"]:
            resolved += 1
        rows.append(d)
    OUT.write_text(json.dumps(rows, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {len(rows)} rows -> {OUT} ({OUT.stat().st_size/1024:.0f} KB)")
    print(f"Normattiva URLs resolved: {resolved}/{len(rows)} ({100*resolved/len(rows):.1f}%)")


if __name__ == "__main__":
    main()
