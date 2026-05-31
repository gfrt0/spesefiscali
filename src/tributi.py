"""Normalize the raw `tributo` column into structured tribute + category.

The RSF mixes tax type (IRPEF, IVA, ACCISA) with delivery mechanism
('CREDITO D'IMPOSTA'). The mapping below splits these into:

- tributo_norm   : atomic or combo identifier (IRPEF, IRES, IRPEF+IRES,
                   IVA, ACCISA, REGISTRO_BOLLO, SUCCESSIONI, SOSTITUTIVA,
                   CREDITO, MISTO, ALTRO)
- categoria      : DIRETTA / INDIRETTA / SOSTITUTIVA / CREDITO_IMPOSTA /
                   MISTA / ALTRO
- tributi_set    : ordered list of base tributi touched by the misura
                   (useful for set-membership filtering)
"""
from __future__ import annotations

MAP = {
    "IRPEF":                                       ("IRPEF",         "DIRETTA",         ["IRPEF"]),
    "IRES":                                        ("IRES",          "DIRETTA",         ["IRES"]),
    "IRPEF/IRES":                                  ("IRPEF+IRES",    "DIRETTA",         ["IRPEF", "IRES"]),
    "IRPEF/IRES/IRAP":                             ("IRPEF+IRES+IRAP","DIRETTA",        ["IRPEF", "IRES", "IRAP"]),
    "IVA":                                         ("IVA",           "INDIRETTA",       ["IVA"]),
    "ACCISA":                                      ("ACCISA",        "INDIRETTA",       ["ACCISA"]),
    "IMPOSTE DI REGISTRO, DI BOLLO E IPOCATASTALI": ("REGISTRO_BOLLO","INDIRETTA",      ["REGISTRO_BOLLO"]),
    "IMPOSTE SU SUCCESSIONI E DONAZIONI":          ("SUCCESSIONI",   "INDIRETTA",       ["SUCCESSIONI"]),
    "IMPOSTA SOSTITUTIVA":                         ("SOSTITUTIVA",   "SOSTITUTIVA",     ["SOSTITUTIVA"]),
    "IMPOSTA SOSTITUTIVA to to":                   ("SOSTITUTIVA",   "SOSTITUTIVA",     ["SOSTITUTIVA"]),
    "CREDITO D'IMPOSTA":                           ("CREDITO",       "CREDITO_IMPOSTA", ["CREDITO"]),
    "CREDITO D’IMPOSTA":                           ("CREDITO",       "CREDITO_IMPOSTA", ["CREDITO"]),
    "IMPOSTE DIRETTE E IVA":                       ("MISTO",         "MISTA",           ["IRPEF", "IRES", "IVA"]),
    "IPOCATASTALI IRPEF":                          ("MISTO",         "MISTA",           ["REGISTRO_BOLLO", "IRPEF"]),
    "ALTRO":                                       ("ALTRO",         "ALTRO",           ["ALTRO"]),
}


def normalize(raw: str) -> dict:
    key = (raw or "").strip()
    if key in MAP:
        norm, cat, members = MAP[key]
    else:
        norm, cat, members = ("ALTRO", "ALTRO", ["ALTRO"])
    return {
        "tributo_norm": norm,
        "categoria":    cat,
        "tributi_set":  members,
    }


if __name__ == "__main__":
    import sqlite3
    from pathlib import Path
    con = sqlite3.connect(Path(__file__).resolve().parent.parent / "db" / "spesefiscali.db")
    unmapped = [r[0] for r in con.execute("SELECT DISTINCT tributo FROM measures") if r[0] not in MAP]
    print(f"Unmapped tributo values: {unmapped or 'none'}")
    print(f"\nCategoria breakdown:")
    from collections import Counter
    c = Counter()
    s = Counter()
    for r in con.execute("SELECT tributo, COALESCE(effetto_2025,0) FROM measures"):
        cat = normalize(r[0])["categoria"]
        c[cat] += 1
        s[cat] += r[1]
    for cat, cnt in c.most_common():
        print(f"  {cat:<18s} {cnt:>4d} misure   {s[cat]:>+12,.0f} mln EUR")
