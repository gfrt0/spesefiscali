"""Extract Tavola 1 from any RSF PDF into a per-year CSV.

The Commissione's per-measure inventory (Tavola 1: Spese fiscali erariali
per missione di spesa) shares the same 13-column layout in editions
2017, 2021, 2022, 2023, 2024. Older / interim editions (2016, 2018, 2019,
2020) use different layouts and are handled by dedicated parsers.

Usage:
    python3 src/parse_rsf.py <year>
    python3 src/parse_rsf.py 2023
    python3 src/parse_rsf.py all                 # all known easy editions
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

import io
import pdfplumber

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "processed"

# Some editions store their landscape pages with rotation=0 in the PDF
# metadata while the underlying glyphs are laid out as if rotated. The
# result is unreadable extraction (text comes out per-cell-reversed).
# Pre-rotating with pypdf gives pdfplumber a sane orientation to work with.
ROTATE_FIX = {
    2018: 90,
    2020: 90,
}

# Per-year (start, end) inclusive page ranges. Generous bounds are fine;
# non-measure rows are filtered downstream. None means "scan whole PDF".
TAVOLA1_RANGE = {
    2016: (21, 68),
    2017: (16, 64),
    2018: (51, 120),
    2019: (77, 124),
    2020: (27, 93),
    2021: (30, 90),
    2022: (24, 86),
    2023: (27, 92),
    2024: (31, 84),
}

EASY_YEARS = sorted(TAVOLA1_RANGE)

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


def extract_row(page, trow, prev_measure_row=None) -> list[str]:
    """Extract one table row. When a cell bbox is None and the previous
    measure row had a value there, inherit it -- this is how pdfplumber
    represents PDF rowspans (one cell visually covering multiple rows)."""
    out = []
    for i, c in enumerate(trow.cells):
        if c is None and prev_measure_row is not None and i < len(prev_measure_row):
            out.append(prev_measure_row[i])
        else:
            out.append(cell_text(page, c))
    return out


def open_pdf(year: int):
    """Open the year's RSF, applying any per-year rotation fix in memory."""
    pdf_path = RAW / f"RSF-{year}.pdf"
    if not pdf_path.exists():
        sys.exit(f"missing {pdf_path}")
    rot = ROTATE_FIX.get(year)
    if not rot:
        return pdfplumber.open(pdf_path)
    from pypdf import PdfReader, PdfWriter
    start, end = TAVOLA1_RANGE[year]
    r = PdfReader(str(pdf_path))
    w = PdfWriter()
    for i, page in enumerate(r.pages):
        if (start - 1) <= i <= (end - 1):
            page.rotate(rot)
        w.add_page(page)
    buf = io.BytesIO()
    w.write(buf); buf.seek(0)
    return pdfplumber.open(buf)


def parse(year: int) -> list[dict]:
    start, end = TAVOLA1_RANGE[year]

    # The year-triplet shown in the financial-effects columns shifts by year.
    # 2024 -> (2025, 2026, 2027); 2023 -> (2024, 2025, 2026); etc.
    triplet = [str(year + i + 1) for i in range(3)]

    rows_out: list[dict] = []
    missione = ""
    prev_measure_row: list[str] | None = None
    with open_pdf(year) as pdf:
        for page_no in range(start, min(end, len(pdf.pages)) + 1):
            page = pdf.pages[page_no - 1]
            for tbl in page.find_tables():
                if len(tbl.rows[0].cells) < 12:
                    continue  # likely not the per-measure table
                for trow in tbl.rows:
                    row = extract_row(page, trow, prev_measure_row)
                    if not row:
                        continue
                    first = row[0]
                    m = MISSIONE_RE.match(first)
                    if m:
                        missione = f"{m.group(1)}: {m.group(2)}".strip()
                        continue
                    if first == "N." or first.startswith("Tavola 1"):
                        continue
                    if not first and row[6:9] == triplet:
                        continue  # year-subheader row
                    if not first.isdigit():
                        # continuation of a long descrizione
                        if rows_out and len(row) > 2 and row[2]:
                            rows_out[-1]["descrizione"] = (
                                rows_out[-1]["descrizione"] + " " + row[2]
                            ).strip()
                        continue
                    rec = {"missione": missione, "rsf_year": year}
                    for i, col in enumerate(COLS):
                        rec[col] = row[i] if i < len(row) else ""
                    rec["page"] = page_no
                    rows_out.append(rec)
                    prev_measure_row = row
    return rows_out


def dedupe(rows: list[dict]) -> list[dict]:
    """Keep the first occurrence of each N.; subsequent ones come from
    other tavole picked up beyond the Tav.1 page range."""
    seen = set(); out = []
    for r in rows:
        n = r.get("n")
        if not n or not n.isdigit() or n in seen:
            continue
        seen.add(n); out.append(r)
    return out


def write_csv(year: int, rows: list[dict]):
    rows = dedupe(rows)
    out = OUT / f"measures_{year}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["rsf_year", "missione"] + COLS + ["page"]
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    ns = sorted({int(r["n"]) for r in rows})
    span = f"{ns[0]}..{ns[-1]}" if ns else "-"
    gaps = [ns[i] for i in range(1, len(ns)) if ns[i] != ns[i-1]+1]
    gap_note = f"  GAPS at {gaps[:3]}{'...' if len(gaps)>3 else ''}" if gaps else ""
    print(f"  {year}: {len(rows)} rows  (N. {span}){gap_note}  -> {out.name}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("year", help="year, or 'all'")
    args = ap.parse_args()
    years = EASY_YEARS if args.year == "all" else [int(args.year)]
    for yr in years:
        if yr not in TAVOLA1_RANGE:
            print(f"  {yr}: skipped (no range registered)")
            continue
        rows = parse(yr)
        write_csv(yr, rows)


if __name__ == "__main__":
    main()
