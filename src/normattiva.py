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
    (r"d\.?\s*l(?:gv?|v)o\.?", "decreto.legislativo"),       # D.Lvo / D.Lgvo (RSF typos)
    (r"d\.?\s*l\.?\s*g\.?\s*v?\.?s\.?", "decreto.legislativo"),
    (r"decreto\s+legislativo", "decreto.legislativo"),
    (r"d\.?\s*l[.:]?(?!\s*g)", "decreto.legge"),
    (r"decreto[-\s]+legge", "decreto.legge"),
    (r"d\.?\s*p\.?\s*r\.?", "decreto.del.presidente.della.repubblica"),
    (r"d\.?\s*m\.?", "decreto.ministeriale"),
    (r"regio\s+decreto", "regio.decreto"),
    (r"r\.?\s*d\.?", "regio.decreto"),
    (r"l\.?\s*c\.?", "legge.costituzionale"),
    (r"legge", "legge"),
    (r"l\.?", "legge"),     # accept bare 'l' too
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

# Article+comma anchor (handles -bis, -ter, "Artt.", "co." for "comma").
ART_RE = re.compile(
    r"\bart(?:\.|icolo|t\.|t)?\s*(?P<art>\d+(?:[\-\s]?(?:bis|ter|quater|quinquies|sexies|septies|octies|novies|decies))?)"
    r"(?:[,\s]+(?:comma|co\.)\s+(?P<com>[\dA-Za-z\-\.]+))?",
    re.IGNORECASE,
)

# Tipo alternation, widened to tolerate the various spacing / abbreviation
# / typo conventions seen across nine RSF editions:
#   D.Lgs. / D.lgs. / D.lgs / D.Lvo / D.Lgvo / Decreto legislativo
#   D.L. / D L / DL / decreto-legge
#   D.P.R. / DPR / DPR.
#   Legge / L. / L  (single capital L when followed by n.NUM)
_TIPO = (
    r"d\.?\s*l(?:gv?|v)o\.?"                          # D.Lvo / D.Lgvo (typo for Lgs)
    r"|d\.?\s*l\s*[.:]?\s*g\s*[.:]?\s*v?\.?s?\.?"      # D.Lgs / D.Lgvs / D.lgs .
    r"|decreto\s+legislativo"
    r"|decreto[-\s]+legge"
    r"|d\.?\s*l[.:]?(?!\s*g|\s*p|\s*m|\s*lgs|\s*lvo|\s*lgvo)"   # D.L. / D.L: (excl. variants)
    r"|d\.?\s*p\.?\s*r\.?"
    r"|d\.?\s*m\.?"
    r"|regio\s+decreto"
    r"|r\.?\s*d\.?"
    r"|legge"
    r"|l\.\s*c\."
    r"|l\.?"
)

_MESE = (r"gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|"
         r"settembre|ottobre|novembre|dicembre")

# Full-form citation:  TIPO + DD MONTH YYYY + n. NUM
CITE_RE = re.compile(
    rf"(?P<tipo>{_TIPO})\s*"
    r"(?P<giorno>\d{1,2})°?\s+"
    rf"(?P<mese>{_MESE})\s+"
    r"(?P<anno>\d{2,4})\s*[,.]?\s*n\s*[.,]?\s*(?P<num>\d+)",
    re.IGNORECASE,
)

# Reversed order:  TIPO [n.] NUM + del + DD MONTH YYYY
#   "legge n. 232 del 11 dicembre 2016"
#   "D.L. n. 41 del 23 febbraio 1995"
#   "DL 351 del 25 settembre 2001"
CITE_NUM_FIRST = re.compile(
    rf"(?P<tipo>{_TIPO})\s*(?:n\s*[.,]\s*)?(?P<num>\d+)\s+del\s+"
    r"(?P<giorno>\d{1,2})°?\s+"
    rf"(?P<mese>{_MESE})\s+"
    r"(?P<anno>\d{4})",
    re.IGNORECASE,
)

# Numeric (slashed or dotted) date:  TIPO + [n.] NUM + del + DD/MM/YYYY
#   "D. Lgs 347 del 31/10/1990"   "Legge 27.12.2006, n. 296"
CITE_NUM_FIRST_NUMDATE = re.compile(
    rf"(?P<tipo>{_TIPO})\s*(?:n\s*[.,]\s*)?(?P<num>\d+)\s+del\s+"
    r"(?P<giorno>\d{1,2})[/.\-](?P<mese>\d{1,2})[/.\-](?P<anno>\d{4})",
    re.IGNORECASE,
)
# "Legge 27.12.2006, n. 296" — date before number
CITE_DATE_FIRST_NUMDATE = re.compile(
    rf"(?P<tipo>{_TIPO})\s*"
    r"(?P<giorno>\d{1,2})[/.\-](?P<mese>\d{1,2})[/.\-](?P<anno>\d{4})\s*[,.]?\s*"
    r"n\s*[.,]\s*(?P<num>\d+)",
    re.IGNORECASE,
)

# Abbreviated year-only forms:
#   "D.P.R. 633/72"  "Legge 604/1954"  "L. 178/2020"  "DL 70-2011"
#   "legge, 413/1991"  (stray comma between tipo and number)
CITE_SHORT = re.compile(
    rf"\b(?P<tipo>{_TIPO})\s*,?\s*(?:n[-\s.,]\s*)?(?P<num>\d{{1,5}})\s*[/\-]\s*(?P<yy>\d{{2,4}})\b",
    re.IGNORECASE,
)
#   "D.L. n. 34 del 2019"  "legge n. 116 del 1995"
#   "D.lgs . N. 347 del 1990"    (stray space-dot before n.)
#   "D.L. n. 330 del 94"         (two-digit year)
CITE_DEL = re.compile(
    rf"\b(?P<tipo>{_TIPO})\s*[.,]?\s*(?:n\s*[.,]\s*)?(?P<num>\d{{1,5}})\s+del\s+(?P<yy>\d{{2,4}})\b",
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


def _norm_anno(yy: str) -> str:
    return yy if len(yy) == 4 else ("19" + yy if int(yy) >= 30 else "20" + yy)


def parse_norma(s: str) -> Parsed:
    """Return the first parseable citation in `s`.

    Preference order:
      1. Full-form citation (TIPO + DD MONTH YYYY + n. NUM)
      2. Testi Unici reference (TUIR/TUA/...)
      3. Abbreviated form ('D.P.R. 633/72' / 'L. 178 del 2020')

    Abbreviated cites carry only the year (no day/month). Normattiva
    accepts year-only URNs of the form 'urn:nir:stato:legge:2020;178' --
    they resolve to the same consolidated text -- so we still produce a
    working URL, with the `data` field set to '<YYYY>' rather than
    '<YYYY>-MM-DD'.
    """
    if not s:
        return Parsed()
    art_m = ART_RE.search(s)
    articolo = art_m.group("art") if art_m else None
    comma = art_m.group("com") if art_m else None

    # Try every full-date pattern in order
    for rx in (CITE_RE, CITE_NUM_FIRST, CITE_DATE_FIRST_NUMDATE, CITE_NUM_FIRST_NUMDATE):
        cite_m = rx.search(s)
        if not cite_m:
            continue
        tipo = _norm_tipo(cite_m.group("tipo"))
        mese_raw = cite_m.group("mese")
        if mese_raw.isdigit():
            mese = mese_raw.zfill(2)
        else:
            mese = MESI[mese_raw.lower()]
        giorno = cite_m.group("giorno").zfill(2)
        data = f"{cite_m.group('anno')}-{mese}-{giorno}"
        if not (art_m and art_m.start() < cite_m.end()):
            articolo = comma = None
        return Parsed(tipo=tipo, data=data, numero=cite_m.group("num"),
                      articolo=articolo, comma=comma, source="cite")

    tu_m = TU_RE.search(s)
    if tu_m:
        key = tu_m.group(1).upper()
        tipo, data, num = TU[key]
        return Parsed(tipo=tipo, data=data, numero=num,
                      articolo=articolo, comma=comma, source="tu")

    # Fall back to abbreviated cite forms (year-only date).
    short_m = CITE_SHORT.search(s) or CITE_DEL.search(s)
    if short_m:
        tipo = _norm_tipo(short_m.group("tipo"))
        anno = _norm_anno(short_m.group("yy"))
        if not (art_m and art_m.start() < short_m.end()):
            articolo = comma = None
        return Parsed(tipo=tipo, data=anno, numero=short_m.group("num"),
                      articolo=articolo, comma=comma, source="cite-short")

    return Parsed()


def parse_all(s: str) -> list[Parsed]:
    """Return every citation found in `s` -- full-date AND abbreviated forms.

    Scans all five citation patterns (CITE_RE, CITE_NUM_FIRST,
    CITE_DATE_FIRST_NUMDATE, CITE_NUM_FIRST_NUMDATE, CITE_SHORT, CITE_DEL),
    builds a Parsed for each match, and dedupes by (tipo, numero, year) so
    that the same act doesn't appear twice when full and short forms
    coexist. TU references (TUIR/TUA/...) are intentionally excluded:
    they're aliases for an istitutiva that is normally cited explicitly
    elsewhere in the norma string.
    """
    if not s:
        return []
    out: list[Parsed] = []
    spans: list[tuple[int, int]] = []  # claimed character spans

    def claimed(a: int, b: int) -> bool:
        return any(not (b <= x or a >= y) for (x, y) in spans)

    # 1. Full-date patterns (textual month, num-first textual, numeric-date variants)
    for rx, fmt in (
        (CITE_RE,                  "tipo-date-num"),
        (CITE_NUM_FIRST,           "tipo-num-date"),
        (CITE_DATE_FIRST_NUMDATE,  "tipo-date-num-numeric"),
        (CITE_NUM_FIRST_NUMDATE,   "tipo-num-date-numeric"),
    ):
        for m in rx.finditer(s):
            if claimed(m.start(), m.end()):
                continue
            spans.append((m.start(), m.end()))
            tipo = _norm_tipo(m.group("tipo"))
            mese_raw = m.group("mese")
            mese = mese_raw.zfill(2) if mese_raw.isdigit() else MESI[mese_raw.lower()]
            giorno = m.group("giorno").zfill(2)
            anno = m.group("anno")
            out.append(Parsed(
                tipo=tipo, data=f"{anno}-{mese}-{giorno}",
                numero=m.group("num"), source="cite",
            ))

    # 2. Year-only forms (abbreviated). Skip spans already claimed by a full-date match.
    for rx in (CITE_SHORT, CITE_DEL):
        for m in rx.finditer(s):
            if claimed(m.start(), m.end()):
                continue
            spans.append((m.start(), m.end()))
            tipo = _norm_tipo(m.group("tipo"))
            anno = _norm_anno(m.group("yy"))
            out.append(Parsed(
                tipo=tipo, data=anno, numero=m.group("num"), source="cite-short",
            ))

    # 3. Upgrade year-only dates with the cached Gazzetta publication date.
    cache = _load_date_cache()
    upgraded: list[Parsed] = []
    for c in out:
        if c.tipo and c.numero and c.data and len(c.data) == 4:
            base = f"urn:nir:stato:{c.tipo}:{c.data};{c.numero}"
            real = cache.get(base)
            if real:
                c = Parsed(tipo=c.tipo, data=real, numero=c.numero,
                           articolo=c.articolo, comma=c.comma, source=c.source)
        upgraded.append(c)

    # 4. Dedupe by (tipo, numero, year) -- prefer the entry with the most precise date.
    by_key: dict[tuple, Parsed] = {}
    for c in upgraded:
        if not (c.tipo and c.numero and c.data):
            continue
        year = c.data[:4]
        key = (c.tipo, c.numero, year)
        prev = by_key.get(key)
        if prev is None or (len(c.data) > len(prev.data)):
            by_key[key] = c
    return list(by_key.values())


def fallback_url(s: str) -> str | None:
    """Best-effort link for citations that don't resolve to a Normattiva URN.

    OPCM / Ordinanze P.C.M. -> Gazzetta Ufficiale search.
    Vienna Conventions      -> UN Treaty Collection page (diplomatic/consular).
    Accordi internazionali  -> Farnesina diplomatic-archive landing page.
    """
    if not s:
        return None
    low = s.lower()
    if "opcm" in low or re.search(r"ordinanza\s*p\.?\s*c\.?\s*m", low):
        # Push the whole cite to GU's search; usually the first hit is correct.
        return "https://www.gazzettaufficiale.it/ricerca/atto/serie_generale?reset=true&searchString=" \
               + quote(s, safe="")
    if "vienna" in low and "convenzion" in low:
        if "diplomati" in low and "consolari" not in low.split("diplomati")[0]:
            # Generic phrasing covering both -> point to diplomatic.
            return "https://treaties.un.org/pages/ViewDetails.aspx?src=TREATY&mtdsg_no=III-3&chapter=3"
        if "consolari" in low:
            return "https://treaties.un.org/pages/ViewDetails.aspx?src=TREATY&mtdsg_no=III-6&chapter=3"
        return "https://treaties.un.org/Pages/Treaties.aspx?id=3&subid=A"
    if "accordi internazionali" in low or "accordi di sede" in low:
        return "https://www.esteri.it/it/politica-estera-e-cooperazione-allo-sviluppo/politica_europea/"
    return None


_DATE_CACHE: dict[str, str] | None = None


def _load_date_cache() -> dict[str, str]:
    """Lazy-load the year-only URN -> publication-date cache built by
    src/fetch_normattiva_dates.py. Returns an empty dict if missing."""
    global _DATE_CACHE
    if _DATE_CACHE is not None:
        return _DATE_CACHE
    import csv as _csv
    from pathlib import Path as _Path
    p = _Path(__file__).resolve().parent.parent / "data" / "processed" / "normattiva_dates.csv"
    if not p.exists():
        _DATE_CACHE = {}
        return _DATE_CACHE
    with p.open(encoding="utf-8") as f:
        _DATE_CACHE = {r["urn"]: r["data_pubblicazione"] for r in _csv.DictReader(f)}
    return _DATE_CACHE


def annotate(norma: str) -> dict:
    p = parse_norma(norma)
    # Upgrade year-only date with the cached Gazzetta publication date.
    if p.tipo and p.data and len(p.data) == 4 and p.numero:
        base = f"urn:nir:stato:{p.tipo}:{p.data};{p.numero}"
        real = _load_date_cache().get(base)
        if real:
            p = Parsed(tipo=p.tipo, data=real, numero=p.numero,
                       articolo=p.articolo, comma=p.comma, source=p.source)
    uniq = parse_all(norma)  # already deduped + year-only upgraded
    # Pick the most recent. String compare on YYYY[-MM-DD] works because
    # year-only entries collate before the same-year full-date variant (which
    # we've already preferred during dedup), and across years the leading
    # digits dominate.
    ultimo = max(uniq, key=lambda c: c.data) if uniq else None
    return {
        "norma_tipo": p.tipo,
        "norma_data": p.data,
        "norma_num":  p.numero,
        "norma_art":  p.articolo,
        "norma_com":  p.comma,
        "norma_urn":  p.urn,
        "norma_url":  p.url or fallback_url(norma),
        "norma_src":  p.source if p.urn else ("fallback" if fallback_url(norma) else p.source),
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
