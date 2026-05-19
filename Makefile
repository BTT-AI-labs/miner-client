.PHONY: run tidy build

build:
	docker buildx build --platform linux/arm64,linux/amd64 -t bttinfergrid/miner-client:0.0.1 --push .