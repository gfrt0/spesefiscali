PYTHON ?= python3
PDF_URL := https://www.mef.gov.it/export/sites/MEF/documenti-pubblicazioni/rapporti-relazioni/documenti/RSF-2024.pdf
PDF := data/raw/RSF-2024.pdf
CSV := data/processed/measures_2024.csv
DB  := db/spesefiscali.db

.PHONY: all fetch parse load serve clean

all: $(DB)

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

serve: $(DB)
	datasette serve $(DB) --metadata metadata.json --port 8001

clean:
	rm -f $(CSV) $(DB)
