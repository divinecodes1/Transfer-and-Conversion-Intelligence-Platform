# A local .env is optional, but when present every Make target sees the same
# service/authentication settings that Docker Compose and Vite read.
ifneq (,$(wildcard ./.env))
include .env
export
endif

.PHONY: install data build test test-pg test-all ingest test-legacy test-api test-agent test-auth \
        test-rbac test-sec test-bi test-obs test-dags test-rag test-k8s test-readiness \
        test-mart test-ai test-web dataset image demo \
        k8s-up rag-up api agent dash evals pg-up pg-build sso-up obs-up down clean

install:      ## install python deps
	pip install -r requirements.txt

data:         ## generate the synthetic transfer portfolio
	python etl/generate_data.py

build: data   ## generate + load into a local DuckDB warehouse, run DQ gates
	python etl/run.py --engine duckdb

test:         ## server-free gates: golden, governance, marts, AI, console, DAGs, manifests
	python tests/golden_projects.py
	python tests/governance_checks.py
	python tests/mart_checks.py
	python tests/readiness_checks.py
	python tests/legacy_reconciliation.py
	python tests/ai_checks.py
	python tests/web_checks.py
	python tests/orchestration_checks.py
	python tests/k8s_checks.py
	python tests/auth_checks.py

test-pg:      ## every gate that needs PostgreSQL (expects pg-up + pg-build)
	python tests/ingestion_checks.py
	python etl/run.py --engine postgres --dsn postgresql://app:dev@localhost:5432/transferops
	python tests/api_checks.py
	python tests/bi_checks.py
	python tests/agent_checks.py
	python tests/rbac_checks.py
	python tests/security_checks.py
	python tests/observability_checks.py
	python tests/rag_checks.py
	python tests/finetuning_checks.py

test-all: test test-pg  ## every gate, both engines

test-api:     ## API contract checks
	python tests/api_checks.py

test-agent:   ## agent evaluation: resolution, abstention, injection, provenance
	python tests/agent_checks.py

test-rbac:    ## entitlement enforcement checks
	python tests/rbac_checks.py

test-sec:     ## auth posture, credential handling, pinning, build context
	python tests/security_checks.py

test-bi:      ## BI layer checks
	python tests/bi_checks.py

test-obs:     ## telemetry, audit trail and least-privilege auditor role
	python tests/observability_checks.py

test-dags:    ## DAG parses, delegates, and gates the run
	python tests/orchestration_checks.py

test-rag:     ## knowledge base builds from the catalogue and stays advisory
	python tests/rag_checks.py

test-k8s:     ## manifests parse, probe, limit and lock down
	python tests/k8s_checks.py

test-mart:    ## the console's rollups agree with the metric layer
	python tests/mart_checks.py

test-readiness: ## readiness weighting, lane re-graining and similarity scoring
	python tests/readiness_checks.py

test-ai:      ## the AI layer stays inside its fence (no model needed)
	python tests/ai_checks.py

test-web:     ## the console holds no SQL, credentials or metric logic
	python tests/web_checks.py

test-auth:    ## registration, verification, recovery, PKCE and SMTP configuration
	python tests/auth_checks.py

dataset:      ## regenerate the fine-tuning instruction pairs from the catalogue
	python fine_tuning/dataset.py
	python fine_tuning/evaluate.py

image:        ## build the container image (one image, three entrypoints)
	docker build -t transferops:dev .

k8s-up: image ## load into kind and apply the manifests
	kind create cluster --name transferops || true
	kind load docker-image transferops:dev --name transferops
	kubectl apply -f kubernetes/transferops.yaml
	kubectl -n transferops rollout status deploy/analytics-api

rag-up:       ## start Qdrant (optional; retrieval runs in-process without it)
	docker compose --profile rag up -d

api:          ## serve the read-only analytics API on :8000 (Swagger at /docs)
	uvicorn api.main:app --reload

agent:        ## serve the reporting assistant on :8100 (POST /ask)
	uvicorn agent.app:app --port 8100 --reload

dash:         ## serve the hand-built dashboards on :8501 (needs `make api` running)
	uvicorn bi.server:app --port 8501 --reload

web-install:  ## install the console's node dependencies (one time)
	cd web && npm install

demo:         ## ONE COMMAND: database + warehouse + API + assistant + console, seeded
	@# For showing the platform to someone. Runs in demo mode, so there is no
	@# sign-in and no Keycloak cold start, and the console's identity switcher
	@# demonstrates entitlement enforcement faster than logging in twice would.
	@# Localhost only -- the deployed path uses enforced authentication.
	pwsh -NoProfile -File scripts/demo.ps1 || powershell -NoProfile -File scripts/demo.ps1

web:          ## serve the React console on :5173 (proxies to `make api` + `make agent`)
	cd web && npm run dev

web-build:    ## typecheck and build the console for production
	cd web && npm run build

ai-refresh:   ## warm the AI caches against the current warehouse vintage
	python -m ai.refresh --job all --trigger manual

evals:        ## agent eval report against a running API
	python agent/evals/run_evals.py

ingest:       ## layered RAW->STAGING->CORE load (ARGS=--corrupt, or --engine postgres)
	python etl/ingest.py $(ARGS)

test-legacy:  ## v0-legacy vs governed reconciliation
	python tests/legacy_reconciliation.py

pg-up:        ## start PostgreSQL (pgvector) via docker
	docker compose up -d

pg-build: data ## load into PostgreSQL (expects pg-up first)
	python etl/run.py --engine postgres --dsn postgresql://app:dev@localhost:5432/transferops

sso-up:       ## start Keycloak too, and enforce authentication
	docker compose --profile sso up -d
	@echo "Realm 'transferops' imported. Verification mail: http://localhost:8025"

obs-up:       ## start Prometheus (:9090) + Grafana (:3000, admin/admin)
	docker compose --profile obs up -d
	@echo "Grafana: http://localhost:3000  dashboard 'Transfer & Conversion Intelligence Platform' (admin/admin)"
	@echo "Scrapes host.docker.internal:8000 and :8100 -- run 'make api' and 'make agent'."

down:         ## stop every profile
	docker compose --profile sso --profile obs down

clean:
	rm -f warehouse*.duckdb data/*.csv
