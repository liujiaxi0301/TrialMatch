.PHONY: up live down reproduce

up:
	TRIALMATCH_MODE=offline docker compose up --build --remove-orphans --wait --wait-timeout 180

live:
	docker compose run --build --rm --no-deps rag-api python -c \
		'import os; from pathlib import Path; assert os.environ["GCP_PROJECT"].strip(), "Set GCP_PROJECT in .env"; assert Path(os.environ["GOOGLE_APPLICATION_CREDENTIALS"]).is_file(), "Copy Google credentials to secrets/google-credentials.json"'
	docker compose run --build --rm trial-processing \
		dvc --cd services/rag_workflow pull index_snapshots/current.json.dvc
	$(MAKE) up
	docker compose exec -T rag-api python -m services.rag_workflow.cli restore-index \
		--input services/rag_workflow/index_snapshots/current.json
	docker compose exec -T rag-api python -m services.rag_workflow.cli index-status
	TRIALMATCH_MODE=live docker compose up --remove-orphans --wait --wait-timeout 180

down:
	docker compose down --remove-orphans

reproduce:
	@test -f services/trial_ingestion/data/raw.dvc || \
		(echo "Missing services/trial_ingestion/data/raw.dvc. See README.md under Data Reproduction."; exit 1)
	docker compose run --build --rm trial-processing \
		dvc --cd services/trial_ingestion pull data/raw.dvc
	docker compose run --build --rm trial-processing python prepare_data.py --from-raw
	$(MAKE) up
