#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [ -f "$ROOT_DIR/.venv/bin/activate" ]; then
    # shellcheck disable=SC1091
    source "$ROOT_DIR/.venv/bin/activate"
fi

if [ -f "$ROOT_DIR/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    source "$ROOT_DIR/.env"
    set +a
fi

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
VITE_HOST="${VITE_HOST:-127.0.0.1}"

# Keep the Vite proxy aligned with the backend configured in .env.
if [ -z "${BACKEND_URL:-}" ]; then
    proxy_host="$HOST"
    case "$proxy_host" in
        0.0.0.0|::) proxy_host="127.0.0.1" ;;
    esac
    export BACKEND_URL="http://${proxy_host}:${PORT}"
fi

backend_pid=""
frontend_pid=""

cleanup() {
    trap - SIGINT SIGTERM EXIT

    for pid in "$backend_pid" "$frontend_pid"; do
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null || true
        fi
    done

    for pid in "$backend_pid" "$frontend_pid"; do
        if [ -n "$pid" ]; then
            wait "$pid" 2>/dev/null || true
        fi
    done
}
trap cleanup EXIT
trap 'exit 130' SIGINT
trap 'exit 143' SIGTERM

echo "Backend: $BACKEND_URL"
echo "Frontend: http://$VITE_HOST:5173"

python fastapi_app.py &
backend_pid=$!

npm --prefix frontend run dev -- --host "$VITE_HOST" &
frontend_pid=$!

# Bash 3 (the macOS default) has no `wait -n`, so poll both services and
# propagate the status of whichever one exits first.
while kill -0 "$backend_pid" 2>/dev/null && kill -0 "$frontend_pid" 2>/dev/null; do
    sleep 1
done

if ! kill -0 "$backend_pid" 2>/dev/null; then
    if wait "$backend_pid"; then
        status=0
    else
        status=$?
    fi
    backend_pid=""
    echo "Backend encerrado (status $status)." >&2
else
    if wait "$frontend_pid"; then
        status=0
    else
        status=$?
    fi
    frontend_pid=""
    echo "Frontend encerrado (status $status)." >&2
fi

exit "$status"
