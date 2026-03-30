.PHONY: start stop restart status logs build clean nuke dev-be dev-fe help check-images pull-missing pull-all

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
