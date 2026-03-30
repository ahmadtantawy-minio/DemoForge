.PHONY: start stop restart status logs build clean nuke dev-be dev-fe help check-images pull-missing pull-all hub-setup hub-seed hub-status hub-push hub-pull hub-trust

start:
	./demoforge.sh start

stop:
	./demoforge.sh stop

restart:
	./demoforge.sh restart

status:
	./demoforge.sh status

logs:
	./demoforge.sh logs

build:
	./demoforge.sh build

clean:
	./demoforge.sh clean

nuke:
	./demoforge.sh nuke

dev-be:
	./demoforge.sh dev:be

dev-fe:
	./demoforge.sh dev:fe

help:
	./demoforge.sh help

## Image management
check-images:
	@python3 check_images.py --mode se

pull-missing:
	@python3 check_images.py --mode se --pull-missing

pull-all:
	@python3 check_images.py --mode se --pull-missing
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

hub-pull:         ## [SE] Pull all custom images from private registry
	@scripts/hub-pull.sh

hub-trust:        ## [One-time] Configure Docker to trust the private registry
	@scripts/hub-trust-registry.sh
