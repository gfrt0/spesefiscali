# spesefiscali

Searchable, filterable database of Italian *spese fiscali* (tax expenditures).
Static web UI + reproducible Python pipeline.

**Live:** *(set the Pages URL here after deploy)*

## Scope

RSF 2024 — the 575 *spese fiscali erariali* catalogued in Tavola 1 of the
[Rapporto annuale sulle spese fiscali 2024](https://www.mef.gov.it/export/sites/MEF/documenti-pubblicazioni/rapporti-relazioni/documenti/RSF-2024.pdf)
(MEF, Commissione per la redazione del rapporto annuale sulle spese fiscali).

Each row carries: identifying number, *norma di riferimento* with link to the
consolidated text on Normattiva, descrizione (cleaned), tributo (normalized
to a clean atomic/combo form), categoria fiscale (DIRETTA / INDIRETTA /
SOSTITUTIVA / CREDITO_IMPOSTA / MISTA / ALTRO), natura, termine di vigenza,
financial effect (2025–2027), beneficiari.

See the **Limiti e cautele** section below before drawing conclusions.

## Quick start

```bash
pip install -r requirements.txt
make all      # download PDF, parse Tavola 1, load SQLite, emit measures.json
make web      # static UI on http://127.0.0.1:8000
```

## Pipeline

| Step | File | Output |
|---|---|---|
| Fetch | (curl in `Makefile`) | `data/raw/RSF-2024.pdf` |
| Parse | `src/parse_rsf2024.py` | `data/processed/measures_2024.csv` (575 rows) |
| Tributo normalization | `src/tributi.py` | (injected at export) |
| Normattiva URN resolution | `src/normattiva.py` | (injected at export; 573/575 = 99.7%) |
| Descrizione cleanup (optional) | `src/clean_descrizioni.py` | `data/processed/descrizioni_clean.csv` |
| Load | `src/load_sqlite.py` | `db/spesefiscali.db` |
| Export for web | `src/export_json.py` | `web/measures.json` |

Sanity check: ΣEffetto2025 over quantified measures = −€115.2 bn, consistent
with the MEF headline ~€119 bn (which includes non-quantifiables and local TEs).

## Optional: descrizione cleanup via Gemini 2.5 Flash on Vertex AI

The RSF PDF occasionally drops inter-word spaces inside cells (`del50%`,
`gliinterventi`). A one-shot pass through Gemini restores them. Output is
character-invariant verified: the model may only add or remove whitespace;
any other change → reject and keep the original.

```bash
pip install -r requirements-cleanup.txt
gcloud auth application-default login                # one-time
export GOOGLE_CLOUD_PROJECT="your-gcp-project-id"
export GOOGLE_CLOUD_LOCATION="us-central1"           # optional
make clean-descr
```

Rejects are logged to `data/processed/descrizioni_review.csv`. Reruns are
idempotent (cached); `--retry-rejects` retries only the previously-rejected
rows.

The cleaned CSV is checked into the repo so cloners don't have to re-pay.

## Deployment (GitHub Pages + Workload Identity Federation)

The repository ships a GitHub Actions workflow that rebuilds `web/measures.json`
from the tracked CSVs and deploys `web/` to Pages on every push. The optional
Gemini cleanup runs only on `workflow_dispatch` with `refresh_descrizioni=true`,
authenticated via WIF (no service-account keys).

### One-time setup

1. Push this repository to GitHub.
2. Repo Settings → Pages → Source: **GitHub Actions**.
3. Run the WIF bootstrap locally (needs `roles/iam.workloadIdentityPoolAdmin`
   and `roles/iam.serviceAccountAdmin` on the GCP project):

   ```bash
   PROJECT_ID=your-gcp-project-id \
   GH_REPO=<your-gh-org-or-user>/spesefiscali \
     bash scripts/setup-gcp-wif.sh
   ```

   It prints the four variables to set on the repo (`gh variable set …`).

That's it. From then on, `git push` to `main` rebuilds and deploys. Trigger
`refresh_descrizioni` from the Actions tab when a new RSF arrives.

## Limiti e cautele

These are reproduced in the UI as a modal (top-right "ⓘ Limiti e cautele").

- **Stime ex ante, non gettito effettivo.** The financial effects are MEF
  Commission forecasts, not realised revenue losses. Uncertainty is large for
  new, non-linear, or behaviourally elastic measures (e.g. Superbonus).
- **Somme non additive.** Σ over measures ≠ revenue recovered if you abolished
  them all. There are interaction effects, behavioural responses, and general
  equilibrium effects. The footer sum also excludes "non quantificabile" rows.
- **`categoria` is a design choice.** In particular, CREDITO_IMPOSTA is kept
  separate from DIRETTA even though tax credits typically offset IRPEF/IRES,
  because that's the question people actually ask. Not a legal distinction.
- **PDF-extraction residuals.** 573/575 descrizioni were spacing-cleaned via
  a character-invariant Gemini pass; the remaining 2 retain source typos.
- **What's missing.** Only RSF Tavola 1 (*spese fiscali erariali*). Excluded:
  local TEs (Tavola 6), cessate-with-residual-effects (Tavola 5), social
  contribution carve-outs, and anything the Commission doesn't classify as a
  spesa fiscale.
- **Normattiva links** point to the *primary* citation (norma istitutiva).
  Many measures have been modified by subsequent acts not always reflected
  in the linked consolidated text.

## Roadmap

- Backfill RSF 2016–2023 + Ceriani 2011, Giavazzi 2012. Each edition needs
  its own parser (column layouts shift). Cross-edition stable IDs keyed on
  the Normattiva URN.
- Resolve parliamentary trace per measure (Camera/Senato bill → final vote).
- Join state-aid measures to RNA (Registro Nazionale Aiuti di Stato)
  beneficiary rolls.

## Sources

- [MEF — RSF 2024](https://www.mef.gov.it/export/sites/MEF/documenti-pubblicazioni/rapporti-relazioni/documenti/RSF-2024.pdf)
- [MEF — Commissione spese fiscali](https://www.mef.gov.it/ministero/commissioni/red_spe_fis/index.html)
- [Normattiva](https://www.normattiva.it)
- [Registro Nazionale Aiuti di Stato](https://www.rna.gov.it)
- [Dipartimento Finanze — statistiche dichiarazioni](https://www.finanze.gov.it/it/statistiche-fiscali/DichiarazioniFiscali-/)

## License

Code: MIT. Data: derived from MEF publications (public domain); database
packaging and cleaned descrizioni under CC BY 4.0. See `LICENSE`.
