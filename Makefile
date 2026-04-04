.PHONY: start stop restart status logs build clean nuke dev-start dev-stop dev-restart dev-status dev-logs dev-be dev-fe dev-hub-api dev-init dev-sim-fa dev-purge-fa dev-as help check-images pull-missing pull-all hub-setup hub-seed hub-status hub-push hub-pull hub-trust seed-licenses

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

dev-init:       ## Generate local dev keys (.env.local) without needing hub-setup
	@if grep -q "DEMOFORGE_HUB_API_ADMIN_KEY" .env.local 2>/dev/null; then \
		echo "DEMOFORGE_HUB_API_ADMIN_KEY already set in .env.local"; \
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
	@KEY="sim-$$(openssl rand -hex 16)"; \
	mkdir -p data/dev-sim; \
	FA_SLUG=$$(echo "$(FA)" | sed 's/[@.]/_/g'); \
	FA_FILE="data/dev-sim/$${FA_SLUG}.env"; \
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
	echo "Error: hub-api not reachable. Run: make dev-hub-api"

dev-as:         ## [Dev] Run backend as a simulated FA. Usage: make dev-as FA=user@min.io
	@if [ -z "$(FA)" ]; then echo "Usage: make dev-as FA=user@min.io"; exit 1; fi
	@FA_SLUG=$$(echo "$(FA)" | sed 's/[@.]/_/g'); \
	FA_FILE="data/dev-sim/$${FA_SLUG}.env"; \
	if [ ! -f "$$FA_FILE" ]; then echo "No credentials for '$(FA)'. Run: make dev-sim-fa FA=$(FA)"; exit 1; fi; \
	cp "$$FA_FILE" .env.sim; \
	echo "Starting backend as $(FA)  (run 'make dev-fe' in another terminal)"; \
	trap 'rm -f .env.sim; echo "Removed .env.sim"' EXIT INT TERM; \
	./demoforge.sh dev:be

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
dev-start:      ## Start DemoForge in dev mode
	./demoforge-dev.sh start

dev-stop:       ## Stop DemoForge (dev mode)
	./demoforge-dev.sh stop

dev-restart:    ## Restart DemoForge in dev mode
	./demoforge-dev.sh restart

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

pull-all:
	@python3 check_images.py --mode fa --pull-missing
	@echo "Custom/platform images: run './demoforge.sh build' to build locally."

## Hub management
hub-setup:        ## First-time hub setup: bucket + IAM + registry + seed templates
	@scripts/hub-setup.sh

hub-seed:         ## Re-seed templates to hub after local changes
	@scripts/hub-seed.sh

hub-status:       ## Show local vs remote template counts, sync config, registry health
	@scripts/hub-status.sh

hub-push:         ## [Dev] Build all custom images and push to private registry
	@scripts/hub-push.sh

hub-push-%:       ## [Dev] Build and push one image, e.g.: make hub-push-inference-sim
	@scripts/hub-push.sh $*

hub-pull:         ## [FA] Pull all custom images from private registry
	@scripts/hub-pull.sh

hub-trust:        ## [One-time] Configure Docker to trust the private registry
	@scripts/hub-trust-registry.sh

seed-licenses:    ## Seed license keys to MinIO bucket
	@scripts/seed-licenses.sh

hub-update:       ## [Dev] Update GCP hub: gateway + templates + images + licenses
	@scripts/hub-update.sh

hub-update-%:     ## [Dev] Update specific: hub-update-gateway, hub-update-templates, hub-update-images
	@scripts/hub-update.sh --$*

## Gateway
gateway:          ## Deploy Cloud Run gateway + VPC (run after fresh GCP deploy)
	@scripts/minio-gcp.sh --gateway

gateway-test:     ## Test hub connectivity locally (simulates Field Architect)
	@scripts/local-hub-test.sh

fa-setup:         ## Field Architect first-time setup (starts hub-connector, pulls images)
	@scripts/fa-setup.sh

update-myip:      ## Update firewall with your current IP
	@MY_IP=$$(curl -sf ifconfig.me) && \
	gcloud compute firewall-rules update allow-myip-to-minio \
	  --source-ranges="$${MY_IP}/32" \
	  --project=minio-demoforge && \
	echo "Updated to $${MY_IP}"
