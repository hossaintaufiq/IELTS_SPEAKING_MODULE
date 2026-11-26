# The whole speaking service in one image: language model (vLLM), speech recognition (Whisper), voice (Kokoro) and the service.
# One GPU, one container. See docs/DEPLOY_SERVER.md. Build from the repository root (compose.yaml does):
#   docker build -f deploy/docker/Dockerfile -t speaking-service .
FROM python:3.12-slim-bookworm

ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

# g++: vLLM compiles some code when it starts.  tini: reaps the processes the models leave behind.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl g++ libgomp1 tini \
 && rm -rf /var/lib/apt/lists/*

# The language model server has its own environment, so its libraries cannot break the service's.
RUN python -m venv /opt/vllm && /opt/vllm/bin/pip install "vllm==0.34.0"

COPY deploy/docker/requirements.txt /tmp/requirements.txt
RUN python -m venv /opt/app && /opt/app/bin/pip install -r /tmp/requirements.txt
# The packages above pull in the CPU "onnxruntime", which shares its files with onnxruntime-gpu: the GPU build must be installed
# last, or the voice runs on the CPU (48 s per sentence instead of 0.2 s).
RUN /opt/app/bin/pip uninstall -y onnxruntime onnxruntime-gpu \
 && /opt/app/bin/pip install "onnxruntime-gpu[cuda,cudnn]==1.22.0" \
 && /opt/app/bin/python -c "import onnxruntime as o; assert 'CUDAExecutionProvider' in o.get_available_providers()"

ENV NLTK_DATA=/opt/nltk_data
RUN /opt/app/bin/python -c "import nltk, sys; sys.exit(0 if nltk.download('punkt_tab', download_dir='/opt/nltk_data', quiet=True) else 1)"

# The voice model is small enough to be part of the image. Whisper and the language model are downloaded at the first start,
# into the "models" volume.
ARG KOKORO_URL=https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0
RUN mkdir -p /opt/models \
 && curl -fsSL --retry 3 -o /opt/models/kokoro-v1.0.onnx "$KOKORO_URL/kokoro-v1.0.onnx" \
 && curl -fsSL --retry 3 -o /opt/models/voices-v1.0.bin "$KOKORO_URL/voices-v1.0.bin"

# Not root. The named volumes take their ownership from these folders.
RUN useradd --create-home --uid 10001 speaking \
 && mkdir -p /app/runs /data/models /data/logs \
 && chown -R speaking:speaking /app/runs /data

WORKDIR /app
# Only these folders: never "COPY . ." (the repository root can hold a private key).
COPY worker ./worker
COPY web ./web
COPY question_bank ./question_bank
COPY eval ./eval
COPY deploy/docker/supervisor.py ./deploy/docker/supervisor.py

# The internal port (monitor, logs) listens inside the container only so that Docker can forward it; compose.yaml publishes it
# on the server's own 127.0.0.1 and nowhere else.
ENV HOST=0.0.0.0 PORT=8080 \
    INTERNAL_HOST=0.0.0.0 INTERNAL_PORT=8081 INTERNAL_ALLOW_REMOTE=1 \
    HF_HOME=/data/models/huggingface LOG_DIR=/data/logs \
    KOKORO_MODEL=/opt/models/kokoro-v1.0.onnx KOKORO_VOICES=/opt/models/voices-v1.0.bin ONNX_PROVIDER=CUDAExecutionProvider \
    MAX_SESSIONS=10 RECYCLE_ON_LEAK=1 RETENTION_DAYS=30

USER speaking
EXPOSE 8080
# "healthy" means ready for tests. The first start downloads several GB, hence the long start period.
HEALTHCHECK --interval=30s --timeout=10s --start-period=30m --retries=3 \
  CMD curl -fsS http://127.0.0.1:8081/health | grep -q '"ready":true'

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/opt/app/bin/python", "/app/deploy/docker/supervisor.py"]
