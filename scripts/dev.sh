#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -f .venv/bin/activate ]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
fi

if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
fi

cleanup() {
    trap - SIGINT SIGTERM EXIT
    jobs -p | xargs -r kill 2>/dev/null
}
trap cleanup SIGINT SIGTERM EXIT

python app.py &
(cd frontend && npm run dev) &

wait
