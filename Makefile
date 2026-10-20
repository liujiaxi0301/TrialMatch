.PHONY: build dev run up down snapshot

build:
	docker compose --profile dev build

dev:
	docker compose run --rm workspace

run:
	docker compose run --rm workspace uv run --frozen \
		python -m services.rag_workflow.cli --mode offline screen \
		--patient-id 060e72d3-912e-55cd-0c92-5faa6cb7a6db \
		--question "Which clinical trials may suit this patient, and what needs review?" \
		--top-k 3 --output artifacts/rag_workflow/demo_offline.json

up:
	docker compose up --wait --wait-timeout 180
	$(MAKE) snapshot

down:
	docker compose down

snapshot:
	docker compose exec -T rag-api uv run --frozen python -c \
		'from pathlib import Path; from services.frontend.vector_demo import LocalVectorDemo; index = LocalVectorDemo().index; result = index.export(Path("artifacts/infra/snapshots") / (index.name + ".json")); print("Saved", result["snapshot"])'
