# The deployed image.
#
# A Dockerfile rather than a buildpack, for two reasons. The repo is two languages --
# a Vite frontend that has to be built and a Python server that serves the result --
# and buildpack auto-detection picks one. And `config.ROOT` is derived from the source
# file's own location (`server/riftbound/config.py` -> two parents up), so the layout
# on disk is part of the contract: `server/`, `web/dist/` and `data/` must be siblings
# under one root. A Dockerfile states that; a buildpack leaves it to be discovered.

# -- the frontend -------------------------------------------------------------
FROM node:22-slim AS web

WORKDIR /web
# Lockfile first, so a change to application source does not reinstall the toolchain.
COPY web/package.json web/package-lock.json ./
RUN npm ci

COPY web/ ./
# `npm run build` is `tsc --noEmit && vite build`: the type check is part of the build
# on purpose, so a type error fails the deploy rather than shipping.
RUN npm run build


# -- the server ---------------------------------------------------------------
FROM python:3.12-slim AS app

# PYTHONUNBUFFERED so logs reach the platform as they happen rather than on flush;
# a crash loop with buffered logs shows an empty log.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    RB_MODE=public \
    RB_HOST=0.0.0.0

WORKDIR /app

COPY pyproject.toml README.md ./
COPY server/ ./server/
# Editable, deliberately. A normal install copies the package into site-packages, and
# `ROOT` would then resolve there -- so the app would look for `data/` and `web/dist`
# inside site-packages and find neither. Editable keeps the source where the layout
# above puts it.
RUN pip install --no-cache-dir -e .

# Rules profiles and the offline card seed are small, versioned, and needed to boot.
COPY data/rules/ ./data/rules/
COPY data/seed/ ./data/seed/

COPY --from=web /web/dist ./web/dist
COPY docker-entrypoint.sh ./
RUN chmod +x docker-entrypoint.sh

# `data/` is where persistent storage mounts. It must be *inside* the root:
# `_under_root` rejects any configured path that escapes it, which is what stops a
# misconfigured RB_DATA_DIR from reading the filesystem.
#
# No `VOLUME` instruction here -- Railway's builder rejects it ("use Railway Volumes
# instead") and it would be a no-op there anyway, since Railway Volumes are declared
# and mounted from the dashboard/`railway.toml`, not from the image. A plain Docker
# `docker run` still needs `-v` at the command line to persist this directory; without
# it the mount point exists but nothing outlives the container.

EXPOSE 8020
ENTRYPOINT ["./docker-entrypoint.sh"]
