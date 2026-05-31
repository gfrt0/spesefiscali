# spesefiscali

Searchable database of Italian tax expenditures (*spese fiscali*).

## Current scope

RSF 2024 only — the 575 *spese fiscali erariali* catalogued in Tavola 1 of
the [Rapporto annuale sulle spese fiscali 2024](https://www.mef.gov.it/export/sites/MEF/documenti-pubblicazioni/rapporti-relazioni/documenti/RSF-2024.pdf)
(Commissione per la redazione del rapporto annuale sulle spese fiscali, MEF).

Each measure has: identifying number, *norma di riferimento*, descrizione,
tributo, termine di vigenza, natura, financial effect (2025–2027),
beneficiari, and whether it has been in force more than 5 years.

## Quick start

```bash
make all      # download PDF, parse Tavola 1, load SQLite, emit measures.json
make web      # static UI on :8000
make serve    # alternative: Datasette on :8001
```

Requires `pdfplumber` and `datasette` (install with
`pip install --user pdfplumber datasette`).

### Optional: clean up descrizione typos via Gemini 2.5 Flash on Vertex

The RSF PDF occasionally drops inter-word spaces inside cells
(`del50%`, `gliinterventi`). A one-shot pass through Gemini restores
them. Output is character-invariant-verified (the model is only allowed
to add or remove whitespace; any other change → reject and keep raw).

```bash
pip install --user -r requirements-cleanup.txt
gcloud auth application-default login                # one-time
export GOOGLE_CLOUD_PROJECT="your-project-id"
export GOOGLE_CLOUD_LOCATION="us-central1"           # optional
make clean-descr                                     # populates measures.json with cleaned text
```

Rejects (model-output failed the invariant twice) are logged to
`data/processed/descrizioni_review.csv`; the raw original is kept for
those rows. The cleaned CSV is cached, so reruns only process new rows.

## Pipeline

1. `src/parse_rsf2024.py` — `pdfplumber.extract_tables()` over pages 31–84
   of the RSF PDF, propagating *missione* headers forward; output
   `data/processed/measures_2024.csv` with 575 rows.
2. `src/load_sqlite.py` — load into `db/spesefiscali.db`, parse financial
   amounts (IT decimal `,`), build FTS5 index on descrizione/norma/beneficiari.
3. `metadata.json` — Datasette facets + column docs.

## Sanity check

Sum of `effetto_2025` over quantified measures: **−€115.2 bn** (RSF headline:
~€119 bn including non-quantifiable + local TEs).

## Roadmap

- Backfill RSF 2016–2023 + Ceriani 2011, Giavazzi 2012 — requires per-edition
  parsers (column layouts shift) and a stable cross-edition measure ID
  derived from *norma di riferimento*.
- Resolve `norma` strings to canonical Normattiva URNs; link to originating
  parliamentary act (AC/AS number) via Camera/Senato APIs.
- Join state-aid measures to RNA (Registro Nazionale Aiuti) beneficiary
  rolls; join IRPEF detrazioni to Dipartimento Finanze aggregate
  dichiarazioni statistics.

## Sources

- MEF — [RSF 2024](https://www.mef.gov.it/export/sites/MEF/documenti-pubblicazioni/rapporti-relazioni/documenti/RSF-2024.pdf)
- MEF — [Commissione spese fiscali](https://www.mef.gov.it/ministero/commissioni/red_spe_fis/index.html)
- [Normattiva](https://www.normattiva.it)
- [Registro Nazionale Aiuti di Stato](https://www.rna.gov.it)
- [Dipartimento Finanze — Dichiarazioni](https://www.finanze.gov.it/it/statistiche-fiscali/DichiarazioniFiscali-/)

## License

Code: MIT. Data: derived from MEF publications (public). Database packaging:
CC BY 4.0.
