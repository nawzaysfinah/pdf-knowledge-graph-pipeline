#!/usr/bin/env bash
# Overnight extraction runner.
# - Prevents system sleep via caffeinate
# - Auto-restarts Ollama if it crashes
# - Auto-restarts extraction if it crashes
# - Stops when all chunks are processed

set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
PYTHON="$REPO/.venv/bin/python"
LOG="$REPO/output/overnight.log"
EXTRACTIONS="$REPO/output/extractions.jsonl"
TOTAL_CHUNKS=1525

log() { echo "$(date '+%Y-%m-%d %H:%M:%S')  $*" | tee -a "$LOG"; }

mkdir -p "$REPO/output"
cd "$REPO"

log "=== Overnight extraction started ==="
log "Repo: $REPO"

# Prevent system and display sleep for the duration
caffeinate -i -s &
CAFF_PID=$!
log "caffeinate PID=$CAFF_PID (system sleep prevented)"

cleanup() {
    log "Shutting down..."
    kill "$CAFF_PID" 2>/dev/null || true
    exit 0
}
trap cleanup SIGINT SIGTERM

ensure_ollama() {
    if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
        log "Ollama not responding — restarting..."
        pkill -f "ollama serve" 2>/dev/null || true
        sleep 3
        ollama serve >> "$LOG" 2>&1 &
        sleep 8
        # Warm up model
        curl -s -X POST http://localhost:11434/api/generate \
            -H 'Content-Type: application/json' \
            -d '{"model":"qwen3:0.6b","prompt":"/no_think\nOK","stream":false}' \
            --max-time 30 > /dev/null 2>&1 || true
        log "Ollama restarted and warmed up"
    fi
}

ensure_ollama

while true; do
    DONE=$(wc -l < "$EXTRACTIONS" 2>/dev/null | tr -d ' ' || echo 0)
    log "Progress: $DONE / $TOTAL_CHUNKS chunks done"

    if [ "$DONE" -ge "$TOTAL_CHUNKS" ]; then
        log "=== All chunks processed! ==="
        break
    fi

    ensure_ollama

    log "Starting extraction (resuming from chunk $DONE)..."
    "$PYTHON" -m pipeline.run_extract_triples >> "$LOG" 2>&1 && {
        log "Extraction exited cleanly."
        break
    } || {
        EXIT_CODE=$?
        log "Extraction crashed (exit $EXIT_CODE) — will restart in 10s..."
        sleep 10
    }
done

log "=== Overnight run complete ==="
kill "$CAFF_PID" 2>/dev/null || true
