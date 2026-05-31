PYTHON ?= python3
PDF_URL := https://www.mef.gov.it/export/sites/MEF/documenti-pubblicazioni/rapporti-relazioni/documenti/RSF-2024.pdf
PDF := data/raw/RSF-2024.pdf
CSV := data/processed/measures_2024.csv
DB  := db/spesefiscali.db

JSON := web/measures.json
CLEAN_CSV := data/processed/descrizioni_clean.csv

.PHONY: all fetch parse load export serve web clean-descr clean

all: $(DB) $(JSON)

fetch: $(PDF)

$(PDF):
	mkdir -p $(dir $@)
	curl -L -o $@ "$(PDF_URL)"

parse: $(CSV)

$(CSV): $(PDF) src/parse_rsf2024.py
	$(PYTHON) src/parse_rsf2024.py

load: $(DB)

$(DB): $(CSV) src/load_sqlite.py
	$(PYTHON) src/load_sqlite.py

export: $(JSON)

$(JSON): $(DB) src/export_json.py
	$(PYTHON) src/export_json.py

clean-descr: $(CLEAN_CSV)

$(CLEAN_CSV): $(CSV) src/clean_descrizioni.py
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
	rm -f $(CSV) $(DB) $(JSON)
