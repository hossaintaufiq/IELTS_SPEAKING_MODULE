#!/usr/bin/env bash
# Upload the project to the rented GPU box WITHOUT secrets or the local venv.
# Usage (from speaking-service/):  bash deploy/vast/upload.sh HOST PORT
# The box belongs to a third party: never send .env, API keys, private keys or real student data.
set -euo pipefail
HOST="${1:?host}"; PORT="${2:?ssh port}"
tar --exclude=.venv --exclude=.env --exclude='*.env' --exclude=runs --exclude=__pycache__ \
    --exclude=.pytest_cache --exclude='eval/data' --exclude='models/cache' -czf - . \
  | ssh -p "$PORT" -i ~/.ssh/vast_ed25519 -o StrictHostKeyChecking=accept-new "root@$HOST" \
      "mkdir -p /root/work/speaking-service && tar -xzf - -C /root/work/speaking-service"
echo "uploaded. Next: ssh in and run deploy/vast/setup_instance.sh"
