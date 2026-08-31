#!/bin/sh
set -eu

INTERVAL_SECONDS="${DIGEST_LOOP_SECONDS:-$(( ${DIGEST_HOURS:-24} * 3600 ))}"

while true; do
  echo "[digest_loop] running channel_digest.py"
  python channel_digest.py
  echo "[digest_loop] sleeping ${INTERVAL_SECONDS}s"
  sleep "$INTERVAL_SECONDS"
done
