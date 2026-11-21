#!/usr/bin/env bash
# Run ONCE on the rented GPU box (over SSH). Installs the runtime, downloads models, starts vLLM.
# The paid clock is running while this executes, so it is written to be quick and to stop on error.
set -euo pipefail

WORK=/workspace
LLM="${LLM:-Qwen/Qwen2.5-7B-Instruct-AWQ}"   # PLACEHOLDER: compare 2-3 models in the benchmark
PORT="${PORT:-8000}"

cd "$WORK"
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv

python -m pip install -q --upgrade pip
python -m pip install -q faster-whisper kokoro-onnx soundfile numpy httpx openai "pipecat-ai[silero,websocket]" fastapi "uvicorn[standard]" websockets vllm

mkdir -p models/cache && cd models/cache
# Kokoro ONNX weights (check the kokoro-onnx README for current file names if these 404).
[ -f kokoro-v1.0.onnx ] || wget -q https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx
[ -f voices-v1.0.bin ]  || wget -q https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin
cd "$WORK"

# Pre-fetch the Whisper model so the benchmark does not time the download.
python - <<'PY'
from faster_whisper import WhisperModel
for name in ("small.en", "large-v3-turbo"):
    WhisperModel(name, device="cuda", compute_type="float16")
    print("cached", name)
PY

# Serve the LLM behind an OpenAI-compatible API. Leave VRAM for Whisper + Kokoro.
nohup python -m vllm.entrypoints.openai.api_server \
  --model "$LLM" --port "$PORT" --gpu-memory-utilization 0.60 --max-model-len 4096 \
  > vllm.log 2>&1 &
echo "Then start the test bench:  HOST=0.0.0.0 PORT=8080 python -m worker.server"
echo "vLLM starting (log: $WORK/vllm.log). Wait for 'Application startup complete', then run the benchmarks."
