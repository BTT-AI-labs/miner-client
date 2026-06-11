.PHONY: run tidy build

build:
	docker buildx build --platform linux/arm64,linux/amd64 -t bttinfergrid/miner-client:1.0.0 --push .