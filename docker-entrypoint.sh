#!/bin/bash
set -euo pipefail

if [ -z "${TRUCK_FINDER_PASSWORD_HASH:-}" ]; then
    printf '%s\n' 'TRUCK_FINDER_PASSWORD_HASH must be set to a bcrypt hash.' >&2
    exit 64
fi
if [ -z "${TRUCK_FINDER_PROXY_SECRET:-}" ]; then
    printf '%s\n' 'TRUCK_FINDER_PROXY_SECRET must be set to a private random token.' >&2
    exit 64
fi
export TRUCK_FINDER_USER="${TRUCK_FINDER_USER:-owner}"
caddy validate --config /app/Caddyfile --adapter caddyfile

pids=()
cleanup() {
    trap - TERM INT
    for pid in "${pids[@]}"; do
        kill -TERM "$pid" 2>/dev/null || true
    done
    wait || true
}
trap cleanup EXIT
trap 'exit 0' TERM INT

python -m rivian_finder.cloud &
pids+=("$!")
caddy run --config /app/Caddyfile --adapter caddyfile &
pids+=("$!")
status=0
wait -n "${pids[@]}" || status=$?
# A child exiting unexpectedly must restart the service even if it returned zero.
if [ "$status" -eq 0 ]; then status=1; fi
exit "$status"
