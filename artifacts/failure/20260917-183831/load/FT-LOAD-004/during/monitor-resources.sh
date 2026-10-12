#!/bin/bash

CASE_DIR="$1"

OUT="$CASE_DIR/during/resource-samples.txt"

: > "$OUT"

for i in $(seq 1 30); do

    echo "===== $(date -Iseconds) =====" >> "$OUT"

    kubectl top pods -n kyverno --containers \
        >> "$OUT" 2>&1 || true

    echo >> "$OUT"

    sleep 10
done
