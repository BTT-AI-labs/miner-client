# Miner Agent

`miner-agent` is the node-side control-plane agent.

It is intended to run beside `vllm` and `dcgm-exporter` in the fixed three-container topology described by the design doc:

- `vllm`: serves inference traffic
- `dcgm-exporter`: exposes GPU metrics
- `miner-agent`: handles registration, heartbeat, challenge flow, and local diagnostics

The current implementation is intentionally narrow. It does not start or stop local model processes. It only observes local state and reports it to `main-api`.
And it's usually deployed by [`miner-cli`](https://github.com/BTT-AI-labs/miner-cli) CLI tool within Docker. 

## What It Does

On startup, `miner-agent`:

1. Loads `${MINER_HOME}/config.json`, or generates a new node identity and wallet identity on first boot.
2. Starts a background loop.
3. Calls `POST /api/miner/register`.
4. Calls `POST /api/miner/heartbeat`.
5. Repeats heartbeat on a fixed interval.
6. Pulls a challenge when `register` or `heartbeat` responses return `challenge_required=true`.

On every heartbeat, it collects:

- local `vllm` health from `/health`
- served model IDs from `/v1/models`
- optional load data from `/load`
- local `dcgm-exporter` Prometheus metrics from `/metrics`

It also exposes a small local HTTP API for liveness, readiness, and inspection.

## Current Request Shape

The implementation already follows the V1 control-plane route layout:

- `POST /api/miner/register`
- `POST /api/miner/heartbeat`
- `GET /api/miner/challenge`
- `POST /api/miner/challenge/verify`

Challenge flow:

1. `register` or `heartbeat` returns `challenge_required=true`.
2. `miner-agent` calls `POST /api/miner/challenge...`.
3. It builds the digest as `sha256(${sgin_str})`.
4. It signs that digest with the locally persisted Ed25519 private key.
5. It submits the answer to `POST /api/miner/challenge/verify`.

## Runtime Configuration

Environment variables currently supported by the code:

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `MAIN_API_BASE_URL` | yes | none | Base URL of `main-api` |
| `MINER_TOKEN` | no | empty | Shared token for miner API auth |
| `MINER_TOKEN_HEADER` | no | `X-Miner-Token` | Header name used for `MINER_TOKEN` |
| `MINER_NAME` | no | hostname | Miner display name sent during register |
| `MINER_PUBLIC_IP` | yes | none | Public IP reported during register for vllm endpoints |
| `MINER_REGION` | no | empty | Region reported during register |
| `MINER_RUNTIME_TYPE` | no | `vllm` | Runtime type reported during register |
| `MINER_HOME` | no | `/root/.miner` | Persistent directory for node identity |
| `MINER_HTTP_HOST` | no | `0.0.0.0` | Bind host for local diagnostics API |
| `MINER_HTTP_PORT` | no | `8080` | Bind port for local diagnostics API |
| `MINER_HEARTBEAT_INTERVAL_SECONDS` | no | `30` | Background heartbeat interval |
| `MINER_REQUEST_TIMEOUT_SECONDS` | no | `10` | HTTP timeout for both probes and control-plane calls |
| `MINER_TARGET_MODEL` | yes | empty | Expected served model ID of HuggingFace |
| `MINER_VLLM_BASE_URL` | yes | `http://127.0.0.1:8000` | Local vLLM base URL |
| `MINER_DCGM_METRICS_URL` | no | `http://dcgm-exporter:9400/metrics` | Local DCGM metrics URL |
| `MODELDOCK_INFERENCE_BASE_URL` | no | empty | Fallback for `MINER_VLLM_BASE_URL` |
| `MODELDOCK_DCGM_EXPORTER_URL` | no | empty | Fallback for `MINER_DCGM_METRICS_URL` |
| `MODELDOCK_DEPLOYMENT_NAME` | no | `local` | Deployment name reported upstream |

Notes:

- Explicit `MINER_*` probe URLs override `MODELDOCK_*` fallback URLs.
- The diagnostics API starts as part of the same process that runs the background agent loop.

## Local HTTP API

The FastAPI app exposes:

- `GET /healthz`: process liveness
- `GET /readyz`: readiness based on identity load and recent successful heartbeat activity
- `GET /v1/miner/status`: current settings plus in-memory state
- `GET /v1/miner/identity`: public view of persisted identity
- `POST /v1/miner/register`: trigger one registration attempt
- `POST /v1/miner/heartbeat`: trigger one heartbeat attempt
- `POST /v1/miner/challenge`: trigger one challenge flow with the default purpose `reverify`

`/readyz` returns `503` when:

- the node is not registered yet
- there is no recent successful heartbeat within `3 * MINER_HEARTBEAT_INTERVAL_SECONDS`
- a challenge is still pending

## Identity Persistence

`miner-agent` stores node identity in `${MINER_HOME}/config.json`.
You should mount a volume via `miner-cli` if you have static `wallet_address` or node info 

Fields currently persisted:

- `node_id`
- `node_key_type`
- `node_public_key`
- `node_private_key`
- `wallet_key_type`
- `wallet_public_key`
- `wallet_private_key`
- `wallet_address`
- `created_at`

Identity details:ewfddd

- `node_id` is derived from the Ed25519 public key as a libp2p-style Peer ID
- challenge signatures use the Ed25519 node private key
- `wallet_address` is derived from a secp256k1 keypair as an EVM-style address
- the file is written with best-effort `0700` directory permissions and `0600` file permissions