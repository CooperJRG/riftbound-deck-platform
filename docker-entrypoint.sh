#!/bin/sh
# Start-up: make sure the card data exists, then serve.
#
# A fresh container has an empty `data/` volume, and the app refuses to start without a
# promoted card bundle -- correctly, since every card id in every saved deck resolves
# through it. So the bundle is built here rather than baked into the image: baked, it
# would be as old as the last deploy, and a set release would need a rebuild to show
# cards that already exist.
set -eu

DATA_DIR="${RB_DATA_DIR:-/app/data}"
BUNDLES="${DATA_DIR}/bundles"

if [ -d "${BUNDLES}/current" ] || [ -f "${BUNDLES}/current.txt" ]; then
  echo "[boot] card bundle present"
else
  echo "[boot] no card bundle — building one"
  # Live upstream first. If it is unreachable the deploy still has to come up, so fall
  # back to the seed committed to the repo: stale cards beat a site that will not start.
  if python -m riftbound.data.pipeline build --promote; then
    echo "[boot] built from upstream"
  else
    echo "[boot] upstream unreachable — falling back to the committed seed"
    python -m riftbound.data.pipeline build --promote --source /app/data/seed/cards-export.json
  fi
fi

# The meta snapshot is deliberately not required. The builder, the card browser and the
# deck library all work without one; Explore and Smart Decks simply say there is no data
# yet, and the scheduler fills it in if RB_META_REFRESH is on.
if [ -f "${DATA_DIR}/meta/current.txt" ] || [ -d "${DATA_DIR}/meta/current" ]; then
  echo "[boot] meta snapshot present"
else
  echo "[boot] no meta snapshot — Explore will be empty until a harvest runs"
fi

# `exec` so uvicorn is PID 1 and receives the platform's SIGTERM directly; without it
# the shell holds PID 1 and every deploy ends in a kill after the grace period.
exec uvicorn riftbound.main:app \
  --host "${RB_HOST:-0.0.0.0}" \
  --port "${PORT:-8020}" \
  --proxy-headers \
  --forwarded-allow-ips '*'
