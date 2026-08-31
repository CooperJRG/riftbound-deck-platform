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

# The meta snapshot is deliberately not required to start. Below this the app builds
# its own: `Services.warm()` promotes the snapshot committed at data/meta-seed the
# moment uvicorn comes up, so a volume with no meta on it renders Explore and Smart
# Decks from a real ~20k-deck archive on the very first request rather than an empty
# screen -- no live harvest needed until one is wanted. This check only reports what
# the volume already has; it does no seeding itself.
if [ -f "${DATA_DIR}/meta/current.txt" ] || [ -d "${DATA_DIR}/meta/current" ]; then
  echo "[boot] meta snapshot present"
else
  echo "[boot] no meta snapshot on the volume yet — will be seeded from the committed archive at startup"
fi

# Trust the platform's proxy headers, so request logs and the cookie's `secure` flag see
# the real scheme rather than the http hop inside the network. Read from the environment
# rather than passed as a CLI flag: uvicorn falls back to this variable when
# --forwarded-allow-ips is omitted, and it sidesteps any question of how a `*` glob
# survives quoting across whatever actually execs this script.
export FORWARDED_ALLOW_IPS="${FORWARDED_ALLOW_IPS:-*}"

# `exec` so uvicorn is PID 1 and receives the platform's SIGTERM directly; without it
# the shell holds PID 1 and every deploy ends in a kill after the grace period.
exec uvicorn riftbound.main:app \
  --host "${RB_HOST:-0.0.0.0}" \
  --port "${PORT:-8020}" \
  --proxy-headers
