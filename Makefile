PYTHON ?= python3

YEARS := 2016 2017 2018 2019 2020 2021 2022 2023 2024
PDFS := $(addprefix data/raw/RSF-,$(addsuffix .pdf,$(YEARS)))
CSVS := $(addprefix data/processed/measures_,$(addsuffix .csv,$(YEARS)))

# Per-year fetch URLs (only the easy 2024 URL is publicized; others vary).
PDF_URL_2016 := https://www.mef.gov.it/export/sites/MEF/documenti-allegati/2017/Rapporto_annuale_sulle_spese_fiscali.pdf
PDF_URL_2017 := https://www.mef.gov.it/export/sites/MEF/documenti-allegati/2018/Rapporto_annuale_sulle_spese_fiscali.pdf
PDF_URL_2018 := https://www.mef.gov.it/export/sites/MEF/documenti-allegati/2019/Rapporto_Spese_fiscali_2018.pdf
PDF_URL_2019 := https://www.mef.gov.it/export/sites/MEF/documenti-allegati/2019/Rapporto_spese_fiscali_2019_definitivo.pdf
PDF_URL_2020 := https://www.mef.gov.it/export/sites/MEF/documenti-allegati/2021/Rapporto-spese-fiscali-nov-2020.pdf
PDF_URL_2021 := https://www.mef.gov.it/export/sites/MEF/documenti-allegati/2022/pdf1_Rapporto-spese-fiscali-2021.pdf
PDF_URL_2022 := https://www.mef.gov.it/export/sites/MEF/documenti-allegati/2022/Rapporto-spese-fiscali-2022.pdf
PDF_URL_2023 := https://www.mef.gov.it/export/sites/MEF/documenti-allegati/2023/Rapporto-spese-fiscali-2023.pdf
PDF_URL_2024 := https://www.mef.gov.it/export/sites/MEF/documenti-pubblicazioni/rapporti-relazioni/documenti/RSF-2024.pdf

DB        := db/spesefiscali.db
JSON      := web/measures.json
PANEL     := web/panel.json
CLEAN_CSV := data/processed/descrizioni_clean.csv

.PHONY: all fetch parse load export serve web clean-descr clean

all: $(DB) $(JSON)

fetch: $(PDFS)

data/raw/RSF-%.pdf:
	mkdir -p $(dir $@)
	curl -L -o $@ "$(PDF_URL_$*)"

parse: $(CSVS)

# Each year's CSV depends on its PDF and the unified parser.
data/processed/measures_%.csv: data/raw/RSF-%.pdf src/parse_rsf.py
	$(PYTHON) src/parse_rsf.py $*

load: $(DB)

$(DB): $(CSVS) src/load_sqlite.py src/normattiva.py
	$(PYTHON) src/load_sqlite.py

export: $(JSON)

$(JSON): $(DB) src/export_json.py src/normattiva.py src/tributi.py src/governi.py
	$(PYTHON) src/export_json.py

clean-descr: $(CLEAN_CSV)

$(CLEAN_CSV): data/processed/measures_2024.csv src/clean_descrizioni.py
	@command -v gcloud >/dev/null || { echo "gcloud CLI not found"; exit 1; }
	@[ -n "$$GOOGLE_CLOUD_PROJECT" ] || { echo "Set GOOGLE_CLOUD_PROJECT"; exit 1; }
	$(PYTHON) src/clean_descrizioni.py
	$(PYTHON) src/export_json.py

serve: $(DB)
	datasette serve $(DB) --metadata metadata.json --port 8001

web: $(JSON)
	@echo "Serving web/ on http://127.0.0.1:8000"
	$(PYTHON) -m http.server --directory web 8000

clean:
	rm -f $(CSVS) $(DB) $(JSON) $(PANEL)
