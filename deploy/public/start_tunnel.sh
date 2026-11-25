#!/usr/bin/env bash
# Puts the PUBLIC port of the speaking service on the internet over https through a Cloudflare Tunnel (certificates are Cloudflare's).
#
#   bash deploy/public/start_tunnel.sh named    production and staging: a fixed hostname you own (needs TUNNEL_TOKEN)
#   bash deploy/public/start_tunnel.sh quick    a random trycloudflare.com address, for a one-off smoke test only
#
# It only ever points at the public port (PORT, default 8080: /v1 and /health). The internal port (INTERNAL_PORT, default 8081: test
# bench, monitor, logs) must never be behind a tunnel that students or ieltsup can reach. Run it in tmux; see docs/DEPLOY_PUBLIC.md.
set -euo pipefail
PUBLIC_PORT="${PORT:-8080}"; INTERNAL_PORT="${INTERNAL_PORT:-8081}"
BIN="${CLOUDFLARED:-/root/cloudflared}"

[ "$PUBLIC_PORT" != "$INTERNAL_PORT" ] || { echo "PORT and INTERNAL_PORT are both $PUBLIC_PORT: refusing to expose the internal port" >&2; exit 1; }
[ -x "$BIN" ] || command -v "$BIN" >/dev/null || { echo "cloudflared not found at $BIN (see docs/DEPLOY_PUBLIC.md, step 1)" >&2; exit 1; }

# The service must be up on the public port first, otherwise the tunnel would publish an error page.
if ! curl -fsS --max-time 5 "http://127.0.0.1:$PUBLIC_PORT/health" >/dev/null; then
  echo "Nothing answers on http://127.0.0.1:$PUBLIC_PORT/health. Start the service first (tmux session web)." >&2; exit 1
fi
# And that port must really be the public one: the test bench page must NOT be there.
if [ "$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "http://127.0.0.1:$PUBLIC_PORT/monitor")" != "404" ]; then
  echo "Port $PUBLIC_PORT also serves /monitor: it is not the public port (SINGLE_PORT=1?). Refusing to publish it." >&2; exit 1
fi

case "${1:-}" in
  named)
    : "${TUNNEL_TOKEN:?set TUNNEL_TOKEN (Cloudflare Zero Trust > Networks > Tunnels > your tunnel > install command). Do not paste it into chat.}"
    echo "Named tunnel. In Cloudflare the public hostname must point at http://localhost:$PUBLIC_PORT (not $INTERNAL_PORT)."
    exec "$BIN" tunnel --no-autoupdate run --token "$TUNNEL_TOKEN" ;;
  quick)
    echo "Quick tunnel: the address is random, changes at every start and has no guarantee. Never give it to students."
    exec "$BIN" tunnel --no-autoupdate --url "http://localhost:$PUBLIC_PORT" ;;
  *) echo "usage: bash deploy/public/start_tunnel.sh named|quick" >&2; exit 2 ;;
esac
