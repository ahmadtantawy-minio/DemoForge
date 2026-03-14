.PHONY: start stop restart status logs build clean nuke dev-be dev-fe help

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
