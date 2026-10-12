#!/bin/bash
set -u

CASE_DIR="$1"

run_level() {

    CONCURRENCY="$1"
    WAVES=2

    RESULT="$CASE_DIR/during/c${CONCURRENCY}-latency.txt"
    RESOURCE="$CASE_DIR/during/c${CONCURRENCY}-resources.txt"

    : > "$RESULT"

    echo "===== concurrency=$CONCURRENCY ====="

    for wave in $(seq 1 "$WAVES"); do

        WAVE_START=$(date +%s%3N)

        for worker in $(seq 1 "$CONCURRENCY"); do
            (
                NAME="ft-load-005-c${CONCURRENCY}-w${wave}-${worker}-$(date +%s%N)"
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
                END=$(date +%s%3N)

                echo "$((END-START)) $RC" >> "$RESULT"

                rm -f "$MANIFEST"
            ) &
        done

        wait

        WAVE_END=$(date +%s%3N)

        echo \
          "concurrency=$CONCURRENCY wave=$wave duration_ms=$((WAVE_END-WAVE_START))" \
          | tee -a "$CASE_DIR/during/high-waves.txt"

        sleep 3
    done

    kubectl top pods -n kyverno --containers \
        > "$RESOURCE" 2>&1 || true

    sleep 15
}

: > "$CASE_DIR/during/high-waves.txt"

run_level 30
run_level 35
run_level 40
