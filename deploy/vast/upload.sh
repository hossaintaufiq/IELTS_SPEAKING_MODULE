#!/usr/bin/env bash
# Upload the service to the rented GPU box WITHOUT secrets, experiments, the local venv or recorded runs.
# Usage (from anywhere in the repo):  bash deploy/vast/upload.sh HOST PORT
#                                     bash deploy/vast/upload.sh --list      only print what would be sent, send nothing
# The box belongs to a third party: never send .env, API keys, private keys or real student data.
#
# What is sent: the files git knows about (tracked, plus new files that .gitignore does not hide), minus the deny list below.
# Two layers on purpose: .gitignore hides the usual secrets, and the deny list here still removes them if a .gitignore line is missing.
# The repo root is the project root, so this script no longer runs from a subfolder: the root holds the SSH key, so it must never
# be "tar the current folder".
set -euo pipefail
cd "$(dirname "$0")/../.."        # the repo root, wherever this is run from

list_files() {
  git ls-files -z --cached --others --exclude-standard \
    | grep -zv -E \
        -e '^(experiments|runs|models/cache|eval/data|\.venv[^/]*|\.model-cache)/' \
        -e '^(ssh|ssh\.pub)$' \
        -e '(^|/)(id_[^/]*|[^/]*\.pem|[^/]*\.key|[^/]*\.env)$' \
        -e '(^|/)(__pycache__|\.pytest_cache)/'
}

if [ "${1:-}" = "--list" ]; then
  list_files | tr '\0' '\n'
  exit 0
fi

HOST="${1:?host}"; PORT="${2:?ssh port}"
list_files \
  | tar --null -T - -czf - \
  | ssh -p "$PORT" -i ~/.ssh/vast_ed25519 -o StrictHostKeyChecking=accept-new "root@$HOST" \
      "mkdir -p /root/work/speaking-service && tar -xzf - -C /root/work/speaking-service"
echo "uploaded. Next: ssh in and run deploy/vast/setup_instance.sh"
