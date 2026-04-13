.PHONY: start stop restart status logs build clean nuke dev-start dev-start-gcp dev-stop dev-restart dev-restart-gcp dev-status dev-logs dev-be dev-fe dev-hub-api dev-init dev-sim-fa dev-purge-fa dev-as dev-connector-pull help check-images pull-missing hub-seed hub-status hub-push hub-push-all hub-pull hub-release hub-release-patch hub-release-minor hub-release-major seed-licenses hub-deploy hub-deploy-api hub-deploy-gateway fa-setup fa-cleanup fa-update

## Field Architect mode (standard)
start:          ## Start DemoForge (FA mode)
	./demoforge.sh start

stop:           ## Stop DemoForge
	./demoforge.sh stop

restart:        ## Restart DemoForge (FA mode)
	./demoforge.sh restart

status:         ## Show running services
	./demoforge.sh status

logs:           ## Tail all logs
	./demoforge.sh logs

build:          ## Build images without starting
	./demoforge.sh build

clean:          ## Stop everything, remove volumes
	./demoforge.sh clean

nuke:           ## Full clean + remove built images
	./demoforge.sh nuke

help:
	./demoforge.sh help

dev-init:       ## Generate local dev keys (.env.local) for use with make dev-start (local hub-api only)
	@if grep -q "DEMOFORGE_HUB_API_ADMIN_KEY" .env.local 2>/dev/null; then \
		echo "DEMOFORGE_HUB_API_ADMIN_KEY already set in .env.local"; \
	elif [ -f .env.hub ]; then \
		echo "GCP hub detected (.env.hub exists) — skipping local admin key (not needed for dev-start-gcp)"; \
	else \
		KEY="hubadm-$$(openssl rand -hex 20)"; \
		echo "DEMOFORGE_HUB_API_ADMIN_KEY=$$KEY" >> .env.local; \
		echo "Generated DEMOFORGE_HUB_API_ADMIN_KEY → .env.local"; \
	fi

dev-hub-api:    ## [Dev] Start hub-api locally on :8000 with hot-reload
	@ADMIN_KEY=$$(grep DEMOFORGE_HUB_API_ADMIN_KEY .env.local 2>/dev/null | cut -d= -f2); \
	if [ -z "$$ADMIN_KEY" ]; then echo "Run: make dev-init first"; exit 1; fi; \
	mkdir -p data/hub-api; \
	cd hub-api && \
	HUB_API_ADMIN_API_KEY="$$ADMIN_KEY" \
	HUB_API_DATABASE_PATH="../data/hub-api/demoforge-hub.db" \
	uvicorn hub_api.main:app --port 8000 --reload

dev-sim-fa:     ## [Dev] Register a simulated FA. Usage: make dev-sim-fa FA=user@min.io
	@if [ -z "$(FA)" ]; then echo "Usage: make dev-sim-fa FA=user@min.io"; exit 1; fi
	@mkdir -p data/dev-sim; \
	FA_SLUG=$$(echo "$(FA)" | sed 's/[@.]/_/g'); \
	FA_FILE="data/dev-sim/$${FA_SLUG}.env"; \
	KEY=$$(grep DEMOFORGE_API_KEY "$$FA_FILE" 2>/dev/null | cut -d= -f2); \
	if [ -n "$$KEY" ]; then \
	  echo "Reusing existing key for $(FA) (delete $$FA_FILE to generate a new one)"; \
	else \
	  KEY="sim-$$(openssl rand -hex 16)"; \
	fi; \
	for URL in http://localhost:8000 http://host.docker.internal:8000; do \
	  RESULT=$$(curl -sf -X POST "$$URL/api/hub/fa/register" \
	    -H "Content-Type: application/json" \
	    -d "{\"fa_id\":\"$(FA)\",\"fa_name\":\"$(FA)\",\"api_key\":\"$$KEY\"}" 2>&1) && \
	  printf "DEMOFORGE_FA_ID=$(FA)\nDEMOFORGE_API_KEY=$$KEY\n" > "$$FA_FILE" && \
	  echo "FA registered at $$URL" && \
	  echo "  fa_id  : $(FA)" && \
	  echo "  api_key: $$KEY" && \
	  echo "  run as: make dev-as FA=$(FA)" && exit 0; \
	done; \
	echo "Error: hub-api not reachable. Run: make dev-start first"

dev-as:         ## [Dev] Run backend as a simulated FA. Usage: make dev-as FA=user@min.io
	@if [ -z "$(FA)" ]; then echo "Usage: make dev-as FA=user@min.io"; exit 1; fi
	@FA_SLUG=$$(echo "$(FA)" | sed 's/[@.]/_/g'); \
	FA_FILE="data/dev-sim/$${FA_SLUG}.env"; \
	if [ ! -f "$$FA_FILE" ]; then echo "No credentials for '$(FA)'. Run: make dev-sim-fa FA=$(FA)"; exit 1; fi; \
	cp "$$FA_FILE" .env.sim; \
	echo "Starting backend as $(FA)  (run 'make dev-fe' in another terminal)"; \
	trap 'rm -f .env.sim; echo "Removed .env.sim"' EXIT INT TERM; \
	./demoforge.sh dev:be

dev-connector-pull: ## [Dev] Build hub-connector from source and restart (no GCR dependency)
	@echo "Building hub-connector from hub-connector/..."
	@docker build -t demoforge-hub-connector:local ./hub-connector
	@docker rm -f hub-connector 2>/dev/null || true
	@HUB_URL=$$(grep DEMOFORGE_HUB_URL .env.hub 2>/dev/null | cut -d= -f2); \
	[ -z "$$HUB_URL" ] && HUB_URL="https://demoforge-gateway-64xwtiev6q-ww.a.run.app"; \
	API_KEY=$$(grep DEMOFORGE_API_KEY .env.hub 2>/dev/null | cut -d= -f2); \
	[ -z "$$API_KEY" ] && API_KEY=$$(grep DEMOFORGE_API_KEY .env.local 2>/dev/null | cut -d= -f2); \
	if [ -z "$$API_KEY" ]; then echo "Error: DEMOFORGE_API_KEY not found in .env.hub or .env.local"; exit 1; fi; \
	docker run -d --name hub-connector --restart=always \
	  -p 8080:8080 \
	  -e "HUB_URL=$$HUB_URL" -e "API_KEY=$$API_KEY" \
	  demoforge-hub-connector:local
	@echo "hub-connector restarted with locally-built image"

dev-purge-fa:   ## [Dev] Purge an FA (hard delete, can re-register). Usage: make dev-purge-fa FA=user@min.io
	@if [ -z "$(FA)" ]; then echo "Usage: make dev-purge-fa FA=user@min.io"; exit 1; fi
	@ADMIN_KEY=$$(grep DEMOFORGE_HUB_API_ADMIN_KEY .env.local 2>/dev/null | cut -d= -f2); \
	if [ -z "$$ADMIN_KEY" ]; then echo "Error: DEMOFORGE_HUB_API_ADMIN_KEY not set. Run: make dev-init"; exit 1; fi; \
	FA_ENC=$$(python3 -c "import urllib.parse; print(urllib.parse.quote('$(FA)'))"); \
	for URL in http://localhost:8000 http://host.docker.internal:8000; do \
	  RESULT=$$(curl -sf -X DELETE "$$URL/api/hub/admin/fas/$$FA_ENC" \
	    -H "X-Api-Key: $$ADMIN_KEY" 2>&1) && \
	  echo "Purged FA '$(FA)' — can be re-registered with: make dev-sim-fa FA=$(FA)" && exit 0; \
	done; \
	echo "Error: hub-api not reachable. Run: make dev-hub-api"

## Dev mode (DEMOFORGE_MODE=dev injected automatically)
dev-start:      ## Start DemoForge in dev mode (local hub-api on :8000)
	DEMOFORGE_HUB_LOCAL=1 ./demoforge-dev.sh start

dev-start-gcp:  ## Start DemoForge in dev mode connected to GCP hub via connector
	@if ! curl -sf http://localhost:8080/health >/dev/null 2>&1 && \
	    ! curl -sf http://host.docker.internal:8080/health >/dev/null 2>&1; then \
	  echo "Warning: hub-connector not detected on :8080 — run 'make fa-setup' first"; \
	fi
	DEMOFORGE_HUB_LOCAL= ./demoforge-dev.sh start

dev-stop:       ## Stop DemoForge (dev mode)
	./demoforge-dev.sh stop

dev-restart:    ## Restart DemoForge in dev mode (local hub-api)
	DEMOFORGE_HUB_LOCAL=1 ./demoforge-dev.sh restart

dev-restart-gcp: ## Restart DemoForge in dev mode (GCP hub)
	DEMOFORGE_HUB_LOCAL= ./demoforge-dev.sh restart

dev-status:     ## Show running services (dev mode)
	./demoforge-dev.sh status

dev-logs:       ## Tail all logs (dev mode)
	./demoforge-dev.sh logs

dev-be:         ## Run backend locally with hot-reload (dev mode)
	./demoforge-dev.sh dev:be

dev-fe:         ## Run frontend locally with hot-reload (dev mode)
	./demoforge-dev.sh dev:fe

## Image management
check-images:
	@python3 check_images.py --mode fa

pull-missing:
	@python3 check_images.py --mode fa --pull-missing

## Hub management
hub-seed:         ## Re-seed templates to hub after local changes
	@scripts/hub-seed.sh

hub-status:       ## Show local vs remote template counts, sync config, registry health
	@scripts/hub-status.sh

hub-push:         ## [Dev] Build and push core images (frontend, backend, data-generator) to GCR
	@scripts/hub-push.sh

hub-push-all:     ## [Dev] Build and push ALL custom images to GCR
	@scripts/hub-push.sh --all

hub-push-%:       ## [Dev] Build and push one image, e.g.: make hub-push-inference-sim
	@scripts/hub-push.sh $*

hub-pull:         ## [FA] Pull all custom images from private registry
	@scripts/hub-pull.sh

seed-licenses:    ## Seed license keys to GCS
	@scripts/seed-licenses.sh

hub-release:      ## [Dev] Full release: commit, tag, push images+templates, deploy hub-api, notify FAs
	@scripts/hub-release.sh $(if $(VERSION),--version $(VERSION),) $(if $(filter major,$(BUMP)),--major,) $(if $(filter minor,$(BUMP)),--minor,) $(if $(NO_IMAGES),--no-images,) $(if $(NO_DEPLOY),--no-deploy,)

hub-release-patch: ## [Dev] Release with patch bump (default)
	@scripts/hub-release.sh --patch

hub-release-minor: ## [Dev] Release with minor bump
	@scripts/hub-release.sh --minor

hub-release-major: ## [Dev] Release with major bump
	@scripts/hub-release.sh --major

hub-update:       ## [Dev] Update GCP hub: gateway + templates + images + licenses
	@scripts/hub-update.sh

hub-update-%:     ## [Dev] Update specific: hub-update-gateway, hub-update-templates, hub-update-images
	@scripts/hub-update.sh --$*

hub-deploy:       ## [Dev] Full GCP deploy: hub-api + gateway Cloud Run + GCS infra
	@scripts/minio-gcp.sh --deploy

hub-deploy-api:   ## [Dev] Redeploy hub-api Cloud Run only (SSH-free, ~2 min)
	@scripts/minio-gcp.sh --deploy-api

hub-deploy-gateway: ## [Dev] Redeploy gateway Cloud Run only (SSH-free, ~1 min)
	@scripts/minio-gcp.sh --deploy-gateway

fa-setup:         ## Field Architect first-time setup (starts hub-connector, pulls images)
	@scripts/fa-setup.sh

fa-update:        ## Pull latest scripts, core images, and restart (FA day-to-day update workflow)
	@scripts/demoforge-update.sh

fa-cleanup:       ## Reset FA local environment for a fresh fa-setup (removes .env.local, stops hub-connector)
	@echo "Stopping hub-connector..."
	@docker rm -f hub-connector 2>/dev/null && echo "  hub-connector stopped" || echo "  hub-connector not running"
	@if [ -f .env.local ]; then \
	  cp .env.local .env.local.bak; \
	  echo "  Backed up .env.local → .env.local.bak"; \
	  rm -f .env.local; \
	  echo "  Removed .env.local"; \
	else \
	  echo "  .env.local not found (nothing to remove)"; \
	fi
	@rm -f .env.sim 2>/dev/null || true
	@echo ""
	@echo "FA environment reset. Run 'make fa-setup' to reconfigure."

