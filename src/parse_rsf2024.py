"""Extract Tavola 1 (per-measure inventory) from RSF 2024 into a CSV.

Tavola 1 spans pages 31--84 (1-indexed). Each page has a 13-column table:
  N. | Norma di riferimento | Descrizione | Tributo |
  Termine vigenza | Natura delle misure |
  Effetti finanziari 2025 | 2026 | 2027 |
  Numero frequenze | Effetti pro capite |
  Soggetti e categorie dei beneficiari | In vigore da piu' di 5 anni

Two PDF quirks worth knowing:

- The default `extract_text` x_tolerance of 3 collapses spaces in this PDF
  because inter-word gaps are unusually tight. We extract each cell via
  bbox-crop with `x_tolerance=1`.
- The "MISSIONE N: NAME" row spans all columns; we propagate it forward
  as the `missione` column for each subsequent measure row.
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

import pdfplumber

PDF = Path(__file__).resolve().parent.parent / "data" / "raw" / "RSF-2024.pdf"
OUT = Path(__file__).resolve().parent.parent / "data" / "processed" / "measures_2024.csv"

TAVOLA1_START = 31
TAVOLA1_END = 84

COLS = [
    "n", "norma", "descrizione", "tributo", "termine_vigenza",
    "natura", "effetto_2025", "effetto_2026", "effetto_2027",
    "numero_frequenze", "effetto_procapite", "beneficiari", "vigore_5plus",
]

MISSIONE_RE = re.compile(r"^MISSIONE\s+(\d+):\s*(.+)$", re.IGNORECASE)


def cell_text(page, bbox) -> str:
    if bbox is None:
        return ""
    txt = page.crop(bbox).extract_text(x_tolerance=1) or ""
    return " ".join(txt.split())


def extract_row(page, table_row) -> list[str]:
    return [cell_text(page, c) for c in table_row.cells]


def parse():
    rows_out = []
    missione = ""
    with pdfplumber.open(PDF) as pdf:
        for page_no in range(TAVOLA1_START, TAVOLA1_END + 1):
            page = pdf.pages[page_no - 1]
            for tbl in page.find_tables():
                for trow in tbl.rows:
                    row = extract_row(page, trow)
                    if not row:
                        continue
                    first = row[0]
                    m = MISSIONE_RE.match(first)
                    if m:
                        missione = f"{m.group(1)}: {m.group(2)}".strip()
                        continue
                    if first == "N." or first.startswith("Tavola 1"):
                        continue
                    if not first and row[6:9] == ["2025", "2026", "2027"]:
                        continue
                    if not first.isdigit():
                        if rows_out and len(row) > 2 and row[2]:
                            rows_out[-1]["descrizione"] = (
                                rows_out[-1]["descrizione"] + " " + row[2]
                            ).strip()
                        continue
                    rec = {"missione": missione}
                    for i, col in enumerate(COLS):
                        rec[col] = row[i] if i < len(row) else ""
                    rec["page"] = page_no
                    rows_out.append(rec)
    return rows_out


def main():
    rows = parse()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["missione"] + COLS + ["page"]
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    ns = sorted({int(r["n"]) for r in rows if r["n"].isdigit()})
    print(f"wrote {len(rows)} rows -> {OUT}")
    print(f"distinct N. values: {len(ns)} (min={ns[0] if ns else '-'}, max={ns[-1] if ns else '-'})")


if __name__ == "__main__":
    sys.exit(main())
