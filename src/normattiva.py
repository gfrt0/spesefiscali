"""Parse Italian legal citations into Normattiva URNs and URLs.

Strategy: extract the *first* (primary/norma istitutiva) citation from a
norma string. Italian tax-law citations follow a small grammar:

    Art. <N>[, comma <M>][, lett. <L>)], <TIPO> <DD MONTH YYYY>, n. <NUM>

plus a fixed set of Testi Unici abbreviations (TUIR, TUA, ...).

URN format (per the Normattiva spec):
    urn:nir:stato:<tipo>:<YYYY-MM-DD>;<NUM>[~art<N>[-com<M>]]

URL for the consolidated/vigente text:
    https://www.normattiva.it/uri-res/N2Ls?<URN-URL-encoded>!vig=
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import quote

MESI = {
    "gennaio": "01", "febbraio": "02", "marzo": "03", "aprile": "04",
    "maggio": "05", "giugno": "06", "luglio": "07", "agosto": "08",
    "settembre": "09", "ottobre": "10", "novembre": "11", "dicembre": "12",
}

# Order matters: longer / more specific patterns first.
TIPO_ATTO_MAP = [
    (r"d\.?\s*lgs\.?", "decreto.legislativo"),
    (r"decreto\s+legislativo", "decreto.legislativo"),
    (r"d\.?\s*l\.?(?!\s*g)", "decreto.legge"),
    (r"decreto[-\s]+legge", "decreto.legge"),
    (r"d\.?\s*p\.?\s*r\.?", "decreto.del.presidente.della.repubblica"),
    (r"d\.?\s*m\.?", "decreto.ministeriale"),
    (r"r\.?\s*d\.?", "regio.decreto"),
    (r"l\.?\s*c\.?", "legge.costituzionale"),
    (r"legge", "legge"),
    (r"l\.", "legge"),
]

# Testi Unici (TU references resolve to a specific norma).
TU = {
    "TUIR":  ("decreto.del.presidente.della.repubblica", "1986-12-22", "917"),
    "TUA":   ("decreto.legislativo",                     "1995-10-26", "504"),
    "TUF":   ("decreto.legislativo",                     "1998-02-24", "58"),
    "TUB":   ("decreto.legislativo",                     "1993-09-01", "385"),
    "TUS":   ("decreto.legislativo",                     "1990-10-31", "346"),
    "TUIVA": ("decreto.del.presidente.della.repubblica", "1972-10-26", "633"),
}

# Article+comma anchor (handles -bis, -ter, ...).
ART_RE = re.compile(
    r"\bart(?:\.|icolo)?\s*(?P<art>\d+(?:[\-\s]?(?:bis|ter|quater|quinquies|sexies|septies|octies|novies|decies))?)"
    r"(?:[,\s]+comma\s+(?P<com>[\dA-Za-z\-\.]+))?",
    re.IGNORECASE,
)

# Main citation matcher: TIPO + date + numero
CITE_RE = re.compile(
    r"(?P<tipo>d\.?\s*lgs\.?|decreto\s+legislativo|d\.?\s*l\.?(?!\s*g)|"
    r"decreto[-\s]+legge|d\.?\s*p\.?\s*r\.?|d\.?\s*m\.?|r\.?\s*d\.?|"
    r"legge|l\.\s*c\.|l\.)\s*"
    r"(?P<giorno>\d{1,2})°?\s+"
    r"(?P<mese>gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre)\s+"
    r"(?P<anno>\d{4})\s*,?\s*n\.\s*(?P<num>\d+)",
    re.IGNORECASE,
)

# TU reference: "TUIR", "TUA", etc., possibly with surrounding punctuation.
TU_RE = re.compile(
    r"\b(TUIR|TUA|TUF|TUB|TUS|TUIVA)\b",
    re.IGNORECASE,
)


@dataclass
class Parsed:
    tipo: str | None = None
    data: str | None = None        # YYYY-MM-DD
    numero: str | None = None
    articolo: str | None = None
    comma: str | None = None
    source: str = ""                # "cite" | "tu" | "none"

    @property
    def urn(self) -> str | None:
        if not (self.tipo and self.data and self.numero):
            return None
        urn = f"urn:nir:stato:{self.tipo}:{self.data};{self.numero}"
        if self.articolo:
            art = re.sub(r"\s+", "", self.articolo.lower()).replace("-", "")
            urn += f"~art{art}"
            if self.comma:
                com = re.sub(r"\s+", "", self.comma.lower()).replace("-", "")
                urn += f"-com{com}"
        return urn

    @property
    def url(self) -> str | None:
        u = self.urn
        if not u:
            return None
        return f"https://www.normattiva.it/uri-res/N2Ls?{quote(u, safe=':;~-')}!vig="


def _norm_tipo(tipo_raw: str) -> str | None:
    t = tipo_raw.strip().lower()
    for pat, canon in TIPO_ATTO_MAP:
        if re.fullmatch(pat, t):
            return canon
    return None


def parse_norma(s: str) -> Parsed:
    """Return the first parseable citation in `s`, preferring full cites over TU."""
    if not s:
        return Parsed()
    art_m = ART_RE.search(s)
    articolo = art_m.group("art") if art_m else None
    comma = art_m.group("com") if art_m else None

    cite_m = CITE_RE.search(s)
    if cite_m:
        tipo = _norm_tipo(cite_m.group("tipo"))
        mese = MESI[cite_m.group("mese").lower()]
        giorno = cite_m.group("giorno").zfill(2)
        anno = cite_m.group("anno")
        data = f"{anno}-{mese}-{giorno}"
        num = cite_m.group("num")
        # only attach art/comma if they appear *before* the cite (primary cite)
        if art_m and art_m.start() < cite_m.end():
            pass  # keep
        else:
            articolo = comma = None
        return Parsed(tipo=tipo, data=data, numero=num,
                      articolo=articolo, comma=comma, source="cite")

    tu_m = TU_RE.search(s)
    if tu_m:
        key = tu_m.group(1).upper()
        tipo, data, num = TU[key]
        return Parsed(tipo=tipo, data=data, numero=num,
                      articolo=articolo, comma=comma, source="tu")

    return Parsed()


def parse_all(s: str) -> list[Parsed]:
    """Return every full citation found in `s` (ignores TU references)."""
    out: list[Parsed] = []
    for m in CITE_RE.finditer(s or ""):
        tipo = _norm_tipo(m.group("tipo"))
        mese = MESI[m.group("mese").lower()]
        giorno = m.group("giorno").zfill(2)
        anno = m.group("anno")
        out.append(Parsed(
            tipo=tipo, data=f"{anno}-{mese}-{giorno}",
            numero=m.group("num"), source="cite",
        ))
    return out


def annotate(norma: str) -> dict:
    p = parse_norma(norma)
    all_cites = parse_all(norma)
    # Deduplicate (same date+numero) and pick the most recent.
    seen = set(); uniq = []
    for c in all_cites:
        key = (c.data, c.numero, c.tipo)
        if key in seen: continue
        seen.add(key); uniq.append(c)
    ultimo = max(uniq, key=lambda c: c.data) if uniq else None
    return {
        "norma_tipo": p.tipo,
        "norma_data": p.data,
        "norma_num":  p.numero,
        "norma_art":  p.articolo,
        "norma_com":  p.comma,
        "norma_urn":  p.urn,
        "norma_url":  p.url,
        "norma_src":  p.source,
        "norma_ultimo_data": ultimo.data if ultimo else p.data,
        "norma_ultimo_urn":  ultimo.urn  if ultimo else None,
        "norma_ultimo_url":  ultimo.url  if ultimo else None,
        "norma_n_cites":     len(uniq),
    }


if __name__ == "__main__":
    import sqlite3
    from pathlib import Path
    con = sqlite3.connect(Path(__file__).resolve().parent.parent / "db" / "spesefiscali.db")
    rows = con.execute("SELECT n, norma FROM measures").fetchall()
    by_src = {"cite": 0, "tu": 0, "none": 0}
    fails = []
    for n, s in rows:
        p = parse_norma(s or "")
        by_src[p.source if p.urn else "none"] = by_src.get(p.source if p.urn else "none", 0) + 1
        if not p.urn and (s or ""):
            fails.append((n, s))
    total = len(rows)
    print(f"parsed: {total - by_src['none']}/{total} "
          f"(cite={by_src['cite']}, tu={by_src['tu']}, fail={by_src['none']})")
    print(f"parse rate: {100*(total - by_src['none'])/total:.1f}%")
    if fails:
        print(f"\nFirst 10 unparsed:")
        for n, s in fails[:10]:
            print(f"  #{n}: {s[:120]}")
