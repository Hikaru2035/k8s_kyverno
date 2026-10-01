#!/bin/bash
set -u

CASE_DIR="$1"

CONCURRENCY=25
BURSTS=4

RESULT="$CASE_DIR/during/latency-ms.txt"
BURST_RESULT="$CASE_DIR/during/burst-summary.txt"

: > "$RESULT"
: > "$BURST_RESULT"

for burst in $(seq 1 "$BURSTS"); do

    BURST_START=$(date +%s%3N)

    for worker in $(seq 1 "$CONCURRENCY"); do
        (
            NAME=$(printf "ft-load-003-b%02d-r%02d" "$burst" "$worker")
            MANIFEST=$(mktemp)

            sed "s/PLACEHOLDER/$NAME/" \
                "$CASE_DIR/before/test-pod.yaml" > "$MANIFEST"

            START=$(date +%s%3N)

            kubectl create \
                --dry-run=server \
                -f "$MANIFEST" \
                >/dev/null 2>&1

            RC=$?
            END=$(date +%s%3N)

            echo "$((END-START)) $RC" >> "$RESULT"

            rm -f "$MANIFEST"
        ) &
    done

    wait

    BURST_END=$(date +%s%3N)

    echo "burst=$burst concurrency=$CONCURRENCY duration_ms=$((BURST_END-BURST_START))" \
        >> "$BURST_RESULT"

    sleep 1
done
