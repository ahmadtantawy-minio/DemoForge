.PHONY: start stop restart status logs build clean nuke dev-start dev-stop dev-restart dev-status dev-logs dev-be dev-fe help check-images pull-missing pull-all hub-setup hub-seed hub-status hub-push hub-pull hub-trust seed-licenses

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
