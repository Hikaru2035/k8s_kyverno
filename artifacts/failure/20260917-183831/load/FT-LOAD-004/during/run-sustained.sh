#!/bin/bash

set -u

CASE_DIR="$1"

DURATION=300
CONCURRENCY=5

RESULT="$CASE_DIR/during/latency-ms.txt"
START_TS=$(date +%s)
END_TS=$((START_TS + DURATION))

: > "$RESULT"

worker() {
    WORKER="$1"
    COUNT=0

    while [ "$(date +%s)" -lt "$END_TS" ]; do

        COUNT=$((COUNT + 1))

        NAME="ft-load-004-w${WORKER}-$(date +%s%N)"

        MANIFEST=$(mktemp)

        sed "s/PLACEHOLDER/$NAME/" \
            "$CASE_DIR/before/test-pod.yaml" \
            > "$MANIFEST"

        START=$(date +%s%3N)

        kubectl create \
            --dry-run=server \
            -f "$MANIFEST" \
            >/dev/null 2>&1

        RC=$?
        FINISH=$(date +%s%3N)

        echo "$((FINISH-START)) $RC $WORKER" >> "$RESULT"

        rm -f "$MANIFEST"

        sleep 1
    done
}

for worker in $(seq 1 "$CONCURRENCY"); do
    worker "$worker" &
done

wait
