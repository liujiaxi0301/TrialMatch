.PHONY: build dev run up down

build:
	docker compose --profile dev build

dev:
	docker compose run --build --rm workspace

run:
	docker compose run --build --rm workspace uv run --frozen \
		python -m services.rag_workflow.cli --mode offline screen \
		--patient-id 060e72d3-912e-55cd-0c92-5faa6cb7a6db \
		--question "Which clinical trials may suit this patient, and what needs review?" \
		--top-k 3 --output artifacts/rag_workflow/demo_offline.json

up:
	docker compose up --build --wait --wait-timeout 90

down:
	docker compose down
