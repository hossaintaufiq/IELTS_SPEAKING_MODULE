#!/usr/bin/env bash
# Run ONCE on the rented GPU box (over SSH, ideally inside tmux). Installs the runtime, downloads
# models, starts vLLM. The paid clock is running while this executes.
#
# Layout (vastai/pytorch image: Ubuntu, Python in /venv/main, no /workspace):
#   /root/work/speaking-service   the project (uploaded by upload.sh)
#   /venv/main                    app env: pipecat, faster-whisper, kokoro-onnx, fastapi
#   /root/vllm-env                separate env for vLLM so it cannot break the image's torch
set -euo pipefail

export PATH=/venv/main/bin:$PATH
WORK=/root/work
APP=$WORK/speaking-service
LLM="${LLM:-Qwen/Qwen2.5-7B-Instruct-AWQ}"   # PLACEHOLDER: compare 2-3 models in the benchmark
PORT="${PORT:-8000}"

cd "$APP"
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv
python --version

echo "== [1/4] vLLM env (background install)"
( python -m venv /root/vllm-env && /root/vllm-env/bin/pip install -q vllm ) > "$WORK/vllm_install.log" 2>&1 &
VLLM_PID=$!

echo "== [2/4] app deps"
python -m pip install -q "pipecat-ai[silero,websocket]==0.0.108" faster-whisper kokoro-onnx soundfile numpy httpx openai requests nltk \
  fastapi "uvicorn[standard]" websockets

python -c "import nltk; nltk.download('punkt_tab', quiet=True)"   # pipecat needs it; do not fetch at runtime

echo "== [3/4] models"
mkdir -p models/cache && cd models/cache
BASE=https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0
[ -f kokoro-v1.0.onnx ] || wget -q $BASE/kokoro-v1.0.onnx
[ -f voices-v1.0.bin ]  || wget -q $BASE/voices-v1.0.bin
cd "$APP"
python - <<'PY'
from faster_whisper import WhisperModel
for name in ("small.en",):
    WhisperModel(name, device="cuda", compute_type="float16")
    print("cached whisper", name)
PY

echo "== [4/4] waiting for vLLM install, then serving $LLM"
wait $VLLM_PID
# Own tmux session: a plain nohup child was killed when the setup tmux window closed.
tmux new-session -d -s vllm "/root/vllm-env/bin/python -m vllm.entrypoints.openai.api_server   --model $LLM --port $PORT --gpu-memory-utilization 0.60 --max-model-len 4096 2>&1 | tee $WORK/vllm.log"
echo "vLLM starting (log: $WORK/vllm.log). Wait for 'Application startup complete'."
echo "Then:  cd $APP && HOST=0.0.0.0 PORT=8080 python -m worker.server"
