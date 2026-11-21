#!/usr/bin/env bash
# Run ONCE on the rented GPU box (inside tmux). Installs everything, downloads models, and starts
# vLLM + the test-bench server. The paid clock is running while this executes.
#
# Layout (vastai/pytorch image: Ubuntu, Python in /venv/main, no /workspace):
#   /root/work/speaking-service   the project (uploaded by upload.sh)
#   /venv/main                    app env: pipecat, faster-whisper, kokoro-onnx, onnxruntime-gpu, fastapi
#   /root/vllm-env                separate env for vLLM so it cannot break the image's torch
#
# Lessons baked in from the first live session: Kokoro must run on the GPU (onnxruntime-gpu 1.22 for
# CUDA 12, not the CPU build), vLLM/web must live in their own tmux sessions, nltk data must be
# pre-fetched, and downloads cost money on some hosts, so each model is fetched once.
set -euo pipefail

export PATH=/venv/main/bin:$PATH
WORK=/root/work
APP=$WORK/speaking-service
LLM="${LLM:-Qwen/Qwen2.5-7B-Instruct-AWQ}"
PORT="${PORT:-8000}"

cd "$APP"
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv
python --version
VRAM_MB=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | head -1)
# Leave about 10 GB for Whisper + Kokoro + CUDA overhead.
UTIL=$(python -c "print(round(min(0.6, max(0.25, ($VRAM_MB-10000)/$VRAM_MB)), 2))")
echo "vLLM GPU memory fraction: $UTIL (of ${VRAM_MB} MiB)"

echo "== [1/5] vLLM env (background install)"
( python -m venv /root/vllm-env && /root/vllm-env/bin/pip install -q vllm ) > "$WORK/vllm_install.log" 2>&1 &
VLLM_PID=$!

echo "== [2/5] app deps"
python -m pip install -q "pipecat-ai[silero,websocket]==0.0.108" faster-whisper kokoro-onnx soundfile numpy httpx openai \
  requests nltk fastapi "uvicorn[standard]" websockets
# kokoro-onnx pulls in the CPU `onnxruntime`, which shares its files with onnxruntime-gpu. The GPU build must be
# installed LAST (after removing both) or the CPU one wins: Kokoro then takes 48 s per sentence instead of 0.2 s.
python -m pip uninstall -y -q onnxruntime onnxruntime-gpu
python -m pip install -q "onnxruntime-gpu==1.22.0"
SPK=/venv/main/lib/python3.12/site-packages
LD_LIBRARY_PATH=$(ls -d $SPK/nvidia/*/lib | tr "\n" ":") python -c "
import onnxruntime as o
p = o.get_available_providers(); print('onnxruntime providers:', p)
assert 'CUDAExecutionProvider' in p, 'GPU onnxruntime is not active'"
python -c "import nltk; nltk.download('punkt_tab', quiet=True)"

echo "== [3/5] models"
mkdir -p models/cache && cd models/cache
BASE=https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0
[ -f kokoro-v1.0.onnx ] || wget -q $BASE/kokoro-v1.0.onnx
[ -f voices-v1.0.bin ]  || wget -q $BASE/voices-v1.0.bin
cd "$APP"
python - <<'PY'
from faster_whisper import WhisperModel
for name in ("large-v3-turbo", "small.en"):
    WhisperModel(name, device="cuda", compute_type="float16")
    print("cached whisper", name)
PY

echo "== [4/5] waiting for the vLLM install, then serving $LLM"
wait $VLLM_PID
tmux new-session -d -s vllm "/root/vllm-env/bin/python -m vllm.entrypoints.openai.api_server \
  --model $LLM --port $PORT --gpu-memory-utilization $UTIL --max-model-len 4096 2>&1 | tee $WORK/vllm.log"

echo "== [5/5] test-bench server (own tmux session)"
cat > "$WORK/start_web.sh" <<'EOF'
#!/usr/bin/env bash
export PATH=/venv/main/bin:$PATH
SP=/venv/main/lib/python3.12/site-packages
export LD_LIBRARY_PATH=$(ls -d $SP/nvidia/*/lib | tr "\n" ":")
export ONNX_PROVIDER=CUDAExecutionProvider
cd /root/work/speaking-service
HOST=0.0.0.0 PORT=8080 exec python -m worker.server 2>&1 | tee /root/work/web.log
EOF
chmod +x "$WORK/start_web.sh"
tmux new-session -d -s web "$WORK/start_web.sh"
echo "SETUP DONE. vLLM is still compiling; wait for 'Application startup complete' in $WORK/vllm.log, then test."
