# Running the service on one GPU server

One container holds the whole service: language model, speech recognition, voice and the exam. ieltsup gets one address and one key.

> **Not yet verified.** The image has not been built or run: the development PC has no Docker. The supervisor is covered by tests with
> stand-in programs; the package list resolves for Linux (vLLM is pinned to the version that ran on the GPU on 2026-11-26). Expect to
> fix small things on the first server.

## What the server needs

| | |
|---|---|
| GPU | 1 NVIDIA card with 24 GB (measured on an RTX 3090: `GPU_TEST_2026-11-26.md`) |
| System | Linux (Ubuntu), 32 GB RAM, 100 GB disk |
| Software | A recent NVIDIA driver (the GPU tests ran on 610 and 615), Docker with the compose plugin, NVIDIA Container Toolkit |
| Network | Outbound access to download the image's packages and the models |

It must be a real or virtual machine. Rented containers (such as vast.ai instances) cannot run Docker inside them.

## First start

```
git clone <this repository> && cd <folder>
cp deploy/docker/.env.example deploy/docker/.env      # fill it in; keep it private
sudo systemctl enable docker                          # so the service comes back after a reboot
docker compose -f deploy/docker/compose.yaml up -d --build
docker compose -f deploy/docker/compose.yaml logs -f  # the supervisor's messages
curl -s http://127.0.0.1:8080/health                  # "ready": true when tests can start
```

The first start downloads several GB of models and can take a long while. Later starts reuse them.

## Public address

The container listens only on the server itself. Give port 8080 an https address with the Cloudflare tunnel
(`DEPLOY_PUBLIC.md`, `deploy/public/start_tunnel.sh`) or a web server on the same machine that forwards WebSockets and does not cut a
connection for at least 30 minutes. Then check it from outside: `python -m eval.check_public --base https://<address> ...`.

Never publish port 8081. To open the monitor from your PC: `ssh -L 8081:localhost:8081 <user>@<server>`, then
`http://localhost:8081/monitor?key=<MONITOR_KEY>`.

## What ieltsup gets

The https address and one key from `SERVICE_API_KEYS`. Endpoints and messages: `API_CONTRACT_V1.md`.

## Running it

| Situation | What happens |
|---|---|
| The service or the language model crashes | It is started again (2 s pause, growing to 60 s if it keeps failing) |
| One of them stops answering for about a minute, or is not ready in time | It is killed and started again |
| The language model restarts | Tests carry on, with scripted questions until it is back |
| GPU memory is not given back after heavy load | The service restarts itself when no test is running |
| The server reboots | Docker starts the container again |
| Logs | `docker compose ... exec speaking tail -f /data/logs/web.log` (also `vllm.log`), or the monitor's Server log tab. One file a day, kept `RETENTION_DAYS` days: they contain what candidates said |
| Update | `git pull`, then `up -d --build`. **Running tests are cut off**: update when no test is running (`/health`, `tests_running`) |
| Stop | `docker compose -f deploy/docker/compose.yaml down` (volumes are kept) |

With one server, tests stop while it is down or being updated.

## To check on the first server

1. The image builds, and `/health` says ready.
2. One full spoken test; `nvidia-smi` shows the voice on the GPU and replies arrive within a few seconds.
3. The load test with 10 candidates: `docker compose ... exec speaking /opt/app/bin/python -m eval.load_test --sessions 10 --api-key <key>`
   (needs the Kokoro files: add `--model /opt/models/kokoro-v1.0.onnx --voices /opt/models/voices-v1.0.bin`).
4. Kill the language model inside the container and see it come back; reboot the server and see the service come back.
5. After the load, `/api/monitor` shows a `gpu_baseline_mb` near the level right after the start.
