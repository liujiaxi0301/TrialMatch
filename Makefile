.PHONY: dirs build up live down reproduce lint fmt format-check lock-check check hooks pre-commit test coverage system-test e2e ci
.DEFAULT_GOAL := up

export LOCAL_UID := $(shell id -u)
export LOCAL_GID := $(shell id -g)
TEST_COMPOSE = docker compose -f docker-compose.yml -f docker-compose.test.yml
PYTHON_PATHS = cloud services evaluation prepare_data.py scripts
PRE_COMMIT = uv tool run pre-commit==4.3.0

dirs:
	mkdir -p artifacts/ms4 secrets

build: dirs
	docker compose build

up: dirs
	TRIALMATCH_MODE=offline docker compose up --build --remove-orphans --wait --wait-timeout 180

live: dirs
	docker compose run --build --rm --no-deps rag-api python -c \
		'import os; from pathlib import Path; assert os.environ["GCP_PROJECT"].strip(), "Set GCP_PROJECT in .env"; assert Path(os.environ["GOOGLE_APPLICATION_CREDENTIALS"]).is_file(), "Copy Google credentials to secrets/google-credentials.json"'
	docker compose run --build --rm trial-processing \
		dvc --cd services/rag_workflow pull index_snapshots/current.json.dvc
	$(MAKE) up
	docker compose exec -T rag-api python -m services.rag_workflow.cli restore-index \
		--input services/rag_workflow/index_snapshots/current.json
	docker compose exec -T rag-api python -m services.rag_workflow.cli index-status
	docker compose exec -T rag-api python -m services.rag_workflow.cli --retrieval-model finetuned build-index
	TRIALMATCH_MODE=live docker compose up --remove-orphans --wait --wait-timeout 180

down:
	docker compose down --remove-orphans

reproduce: dirs
	@test -f services/trial_ingestion/data/raw.dvc || \
		(echo "Missing services/trial_ingestion/data/raw.dvc. See README.md under Data Reproduction."; exit 1)
	docker compose run --build --rm trial-processing \
		dvc --cd services/trial_ingestion pull data/raw.dvc
	docker compose run --build --rm trial-processing python prepare_data.py --from-raw
	$(MAKE) up

lint: dirs
	$(TEST_COMPOSE) run --build --rm --no-deps -T api-tests \
		ruff check --no-cache --config ruff.toml $(PYTHON_PATHS)
	bash -n scripts/ms4/check_coverage.sh
	docker compose config --quiet
	$(TEST_COMPOSE) config --quiet

fmt:
	uv tool run ruff==0.17.1 format --no-cache --config ruff.toml $(PYTHON_PATHS)
	docker/frontend/node_modules/.bin/prettier --write 'services/frontend/**/*.{js,css,html}'

format-check: dirs
	$(TEST_COMPOSE) run --build --rm --no-deps -T api-tests \
		ruff format --check --no-cache --config ruff.toml $(PYTHON_PATHS)
	$(TEST_COMPOSE) run --build --rm --no-deps -T browser-tests npm run format:check

lock-check:
	# Each service selects its own Python, independent of the CI runner default.
	@for project_file in docker/*/pyproject.toml; do \
		env -u UV_PYTHON uv lock --check --project "$${project_file%/*}" || exit $$?; \
	done

# Fast local checks run automatically before a commit after make hooks.
check:
	$(MAKE) lint
	$(MAKE) format-check
	$(MAKE) test

hooks:
	$(PRE_COMMIT) install --allow-missing-config

pre-commit:
	$(PRE_COMMIT) run --all-files

test: coverage

coverage: dirs
	bash scripts/ms4/check_coverage.sh

# Recreates the local Chroma container, preserving its named data volume.
system-test:
	docker compose exec -T rag-api python - write < scripts/ms4/check_chroma.py
	docker compose up --no-deps --force-recreate --wait --wait-timeout 180 -d rag-chromadb
	docker compose exec -T rag-api python - read < scripts/ms4/check_chroma.py
	docker compose exec -T rag-api python - < scripts/ms4/check_index_switch.py

# The application must already be healthy (make up).
e2e: dirs
	$(TEST_COMPOSE) run --build --rm --no-deps -T browser-tests

# Sequential, so make -j cannot race startup against browser tests.
ci:
	$(MAKE) build
	$(MAKE) pre-commit
	$(MAKE) up
	$(MAKE) system-test
	$(MAKE) e2e
