.PHONY: build dev run up live down snapshot pull-index restore-index

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

live:
	$(MAKE) up
	$(MAKE) restore-index
	docker compose -f docker-compose.yml -f docker-compose.live.yml up --wait --wait-timeout 180

down:
	docker compose down

snapshot:
	docker compose exec -T rag-api uv run --frozen python -c \
		'from pathlib import Path; from services.frontend.vector_demo import LocalVectorDemo; index = LocalVectorDemo().index; result = index.export(Path("artifacts/infra/snapshots") / (index.name + ".json")); print("Saved", result["snapshot"])'

pull-index:
	uv run --env-file .env --frozen --group versioning \
		dvc --cd services/rag_workflow pull index_snapshots/current.json.dvc

restore-index:
	docker compose exec -T rag-api python -m services.rag_workflow.cli restore-index \
		--input services/rag_workflow/index_snapshots/current.json
	docker compose exec -T rag-api python -m services.rag_workflow.cli index-status
