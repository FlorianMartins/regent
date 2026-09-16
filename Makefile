.DEFAULT_GOAL := help
SHELL := /bin/bash

VENV ?= .venv
PY   := $(VENV)/bin/python
PIP  := $(VENV)/bin/pip
BIN  := $(VENV)/bin
IMAGE ?= regent:local
COMPOSE := docker compose -f infra/compose/docker-compose.yml

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-16s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

$(VENV):
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip

.PHONY: install
install: $(VENV) ## Create the virtualenv and install the project with the dev and docs extras
	$(PIP) install -e ".[dev,docs]"
	@echo "✅ ready — run '$(BIN)/regent --help'"

.PHONY: clean
clean: ## Remove build, cache and report artefacts (keeps the ledger)
	rm -rf build dist *.egg-info reports .coverage coverage.xml htmlcov site
	rm -rf .pytest_cache .mypy_cache .ruff_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +

# ---------------------------------------------------------------------------
# Quality gates — the same commands the CI pipeline runs
# ---------------------------------------------------------------------------

.PHONY: lint
lint: ## Lint the Python code, the formatting and the GitHub Actions workflows
	$(BIN)/ruff check .
	$(BIN)/ruff format --check .
	$(BIN)/actionlint

.PHONY: format
format: ## Format the code and fix what can be fixed
	$(BIN)/ruff format .
	$(BIN)/ruff check --fix .

.PHONY: typecheck
typecheck: ## Static type checking (mypy strict)
	$(BIN)/mypy

.PHONY: test
test: ## Run the test suite with coverage (offline: replay provider, fake GitHub)
	$(BIN)/pytest --cov=regent --cov-report=term-missing

.PHONY: sast
sast: ## Static security analysis of our own code and dependencies
	$(BIN)/bandit -q -c pyproject.toml -r regent
	# --strict would fail on the editable install of the project itself.
	$(BIN)/pip-audit --skip-editable

.PHONY: secrets
secrets: ## Scan the git history for leaked credentials (needs gitleaks on the PATH)
	@if command -v gitleaks >/dev/null 2>&1; then \
		gitleaks git --redact --no-banner .; \
	else \
		echo "gitleaks not installed — https://github.com/gitleaks/gitleaks#installing (CI runs it anyway)"; \
	fi

.PHONY: iac-scan
iac-scan: ## Scan the infrastructure code and the Dockerfile with CloudGuard-IaC
	$(BIN)/cloudguard full-scan infra Dockerfile --fail-on medium

.PHONY: policy
policy: ## Validate the mandates (invariants) and run the Conftest policies when available
	$(BIN)/regent policy-check
	@if command -v conftest >/dev/null 2>&1; then \
		conftest verify -p policies/rego && \
		conftest test -p policies/rego --parser yaml policies/mandates; \
	else \
		echo "conftest not installed — https://www.conftest.dev/install/ (CI runs it anyway)"; \
	fi

.PHONY: evals
evals: ## Run the offline evaluation suite (add EVALS_LIVE=1 to use the real provider)
	$(BIN)/regent evals $(if $(EVALS_LIVE),--live,) --report reports/evals.json

.PHONY: docs
docs: ## Build the documentation site (strict: a broken link fails)
	$(BIN)/mkdocs build --strict

.PHONY: docs-serve
docs-serve: ## Serve the documentation locally on http://127.0.0.1:8000
	$(BIN)/mkdocs serve

.PHONY: check
check: lint typecheck test sast iac-scan policy evals docs ## Everything the CI pipeline checks
	@echo "✅ all checks passed"

# ---------------------------------------------------------------------------
# Running it
# ---------------------------------------------------------------------------

.PHONY: demo
demo: ## Run the guided demo (agents against a vulnerable example, replay provider)
	@if [ -x examples/demo/run.sh ]; then examples/demo/run.sh; else echo "examples/demo/run.sh not present"; fi

.PHONY: serve
serve: ## Start the control-plane API locally (reads .env if present)
	set -a; [ -f .env ] && . ./.env; set +a; $(BIN)/regent serve

.PHONY: ledger-verify
ledger-verify: ## Re-hash the audit ledger and fail if it was tampered with
	$(BIN)/regent ledger verify $${REGENT_LEDGER:-.regent/ledger.jsonl}

.PHONY: docker
docker: ## Build the container image and scan the Dockerfile with CloudGuard
	docker build -t $(IMAGE) .
	$(BIN)/cloudguard scan-docker Dockerfile
	docker run --rm $(IMAGE) --version

.PHONY: compose-up
compose-up: ## Start the local stack: API, Prometheus, Grafana (:3000), OTel collector
	$(COMPOSE) up --build -d
	@echo "API http://127.0.0.1:8080/healthz · Grafana http://127.0.0.1:3000 (admin/admin) · Prometheus http://127.0.0.1:9090"

.PHONY: compose-down
compose-down: ## Stop the local stack and remove its containers (volumes are kept)
	$(COMPOSE) down

.PHONY: build
build: ## Build the wheel and the sdist
	$(PIP) install --quiet build twine
	$(PY) -m build
	$(BIN)/twine check dist/*
