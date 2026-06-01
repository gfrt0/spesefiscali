# spesefiscali

Searchable, filterable cross-edition database of Italian *spese fiscali*
(tax expenditures). Static web UI + reproducible Python pipeline.

**Live:** https://gfrt0.github.io/spesefiscali/

## Scope

Tavola 1 of every *Rapporto annuale sulle spese fiscali* from RSF 2016
through RSF 2024 — roughly five thousand *spese fiscali erariali*
across nine editions, with a year selector that swaps editions in place
and a cross-edition stable ID so the same measure can be tracked over
time.

Each row carries: identifying number; *norma di riferimento* with link
to the consolidated text on Normattiva; descrizione (spacing-cleaned);
tributo (normalised) and categoria fiscale; natura; termine di vigenza
(structured); financial effects for the three forecast years T+1 / T+2
/ T+3 relative to the edition year; beneficiari; page number with
deep-link into the source PDF; and two governo attributions — *governo
istitutore* (executive at the date of the istitutiva) and *governo
ultimo intervento* (executive at the most recent dated act cited in
the norma string).

See the **Limiti e cautele** modal in the UI before drawing conclusions.

## Quick start

```bash
pip install -r requirements.txt
make all      # download PDFs, parse Tavola 1 of each edition, load SQLite, emit JSON
make web      # static UI on http://127.0.0.1:8000
```

## Pipeline

| Step | File | Output |
|---|---|---|
| Fetch PDFs | `Makefile` (curl) | `data/raw/RSF-{year}.pdf` × 9 |
| Parse | `src/parse_rsf.py {year}` | `data/processed/measures_{year}.csv` |
| Tributo normalisation | `src/tributi.py` | (injected at export) |
| Vigenza normalisation | `src/vigenza.py` | (injected at export) |
| Normattiva URN resolution | `src/normattiva.py` | (injected at export; 100% across all editions) |
| Year-only URN → publication date cache | `src/fetch_normattiva_dates.py` | `data/processed/normattiva_dates.csv` |
| Governo attribution | `src/governi.py` | (injected at export) |
| Descrizione cleanup (optional) | `src/clean_descrizioni.py` | `data/processed/descrizioni_clean_{year}.csv` |
| Load | `src/load_sqlite.py` | `db/spesefiscali.db` |
| Export for web | `src/export_json.py` | `web/measures_{year}.json`, `web/panel.json`, `web/years.json` |

Cross-edition stable IDs (`measure_uid`) key on tipo+number+article
+comma anchor of the istitutiva, with year-level date granularity.
The UI uses them for the per-measure trend data underlying the column
formatters and for tracking measures whose number-of-the-day shifts
between editions.

## Optional: descrizione cleanup via Gemini 2.5 Flash on Vertex AI

The RSF PDFs occasionally drop inter-word spaces inside cells
(`del50%`, `gliinterventi`). A pass through Gemini restores them.
Output is character-invariant verified: the model may only add or
remove whitespace; any other change → reject and keep the original.

```bash
pip install -r requirements-cleanup.txt
gcloud auth application-default login                # one-time
export GOOGLE_CLOUD_PROJECT="your-gcp-project-id"
export GOOGLE_CLOUD_LOCATION="us-central1"           # any Vertex AI region
make clean-descr                                     # all nine editions
# or: python src/clean_descrizioni.py --year 2022    # a single edition
```

Per-year caches: `descrizioni_clean_{year}.csv`. Rejects are logged to
`descrizioni_review_{year}.csv`. Reruns are idempotent (cached);
`--retry-rejects` retries only the previously-rejected rows.

The cleaned CSVs are checked into the repo so cloners don't have to
re-pay the API cost.

## Deployment (GitHub Pages + Workload Identity Federation)

A GitHub Actions workflow rebuilds the JSON outputs from the tracked
CSVs and deploys `web/` to Pages on every push. The optional Gemini
cleanup runs only on `workflow_dispatch` with
`refresh_descrizioni=true`, authenticated via WIF (no service-account
keys).

### One-time setup

1. Push this repository to GitHub.
2. Repo Settings → Pages → Source: **GitHub Actions**.
3. Run the WIF bootstrap locally (needs
   `roles/iam.workloadIdentityPoolAdmin` and
   `roles/iam.serviceAccountAdmin` on the GCP project):

   ```bash
   PROJECT_ID=<your-gcp-project-id> \
   GH_REPO=<your-gh-org-or-user>/spesefiscali \
     bash scripts/setup-gcp-wif.sh
   ```

   It prints the four variables to set on the repo (`gh variable set …`).

`git push` to `main` rebuilds and deploys. Trigger `refresh_descrizioni`
from the Actions tab when a new RSF arrives.

## Limiti e cautele

Reproduced in the UI as a modal (top-right "ⓘ Limiti e cautele").

- **Stime ex ante, non gettito effettivo.** The financial effects are
  MEF Commission forecasts, not realised revenue losses. Uncertainty
  is large for new, non-linear, or behaviourally elastic measures
  (e.g. Superbonus).
- **Somme non additive.** Σ over measures ≠ revenue recovered if you
  abolished them all. Interaction effects, behavioural responses, and
  general equilibrium effects all bite.
- **`categoria` is a design choice.** CREDITO_IMPOSTA is kept separate
  from DIRETTA even though tax credits typically offset IRPEF/IRES,
  because that's the question people actually ask. Not a legal
  distinction.
- **Governo (ult.) is a parser inference.** It is the executive in
  charge at the *most recent dated act* the RSF norma string cites for
  that measure. Measures whose RSF cell prints only the istitutiva
  collapse to that older government even when proroghe exist outside
  the cell. See the "Aggiornamenti all'articolo" roadmap item.
- **PDF-extraction residuals.** All 5000-odd descrizioni went through
  the character-invariant Gemini pass; a small tail retains source
  typos when the model couldn't restore spacing without changing
  non-space characters.
- **What's missing.** Only RSF Tavola 1 (*spese fiscali erariali*).
  Excluded: local TEs (Tavola 6), cessate-with-residual-effects
  (Tavola 5), social-contribution carve-outs, and anything the
  Commission doesn't classify as a spesa fiscale.

## Roadmap

- Article-level "Aggiornamenti all'articolo" scrape on Normattiva to
  enrich *governo ultimo intervento* with proroghe that aren't printed
  in the RSF cell.
- Cumulative-cost chart (rank vs cumulative share of |Σ effetto|).
- Row-detail side panel with a properly sized cross-edition sparkline.
- Spese fiscali locali (Tavola 6).
- Join state-aid measures to RNA (Registro Nazionale Aiuti di Stato)
  beneficiary rolls; Dipartimento Finanze take-up statistics.

## Sources

- [MEF — RSF 2024](https://www.mef.gov.it/export/sites/MEF/documenti-pubblicazioni/rapporti-relazioni/documenti/RSF-2024.pdf) (and the 2016–2023 editions, linked from the Makefile)
- [MEF — Commissione spese fiscali](https://www.mef.gov.it/ministero/commissioni/red_spe_fis/index.html)
- [Normattiva](https://www.normattiva.it)
- [Registro Nazionale Aiuti di Stato](https://www.rna.gov.it)
- [Dipartimento Finanze — statistiche dichiarazioni](https://www.finanze.gov.it/it/statistiche-fiscali/DichiarazioniFiscali-/)

## License

Code: MIT. Data: derived from MEF publications (public domain);
database packaging and cleaned descrizioni under CC BY 4.0. See
`LICENSE`.
