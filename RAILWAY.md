# Railway deployment

- **Region:** `europe-west4` (set in Railway project settings).
- **Start:** Railpack uses the `Procfile` or `railway.toml` (`uvicorn app.main:app --host 0.0.0.0 --port $PORT`).
- **Image size:** PyTorch is installed as **CPU-only** via `railpack.json` so the image stays under the 4 GB limit. Do not add `torch` to `requirements.txt`; it is installed in the custom install step.

## Required variables

Set these in **Railway → your service → Variables** (Railway does not read `.env` from the repo):

| Variable | Description |
|----------|-------------|
| `RB_STORAGE_BACKEND` | `postgres` |
| `RB_DATABASE_URL` | Supabase Postgres connection string (pooler) |
| `RB_SUPABASE_URL` | Supabase project URL (e.g. `https://xxxx.supabase.co`) |
| `RB_SUPABASE_ANON_KEY` | Supabase **anon** (public) key — required for login; copy from Supabase Dashboard → Settings → API |
| `RB_SUPABASE_JWKS_URL` | `https://<project>.supabase.co/auth/v1/.well-known/jwks.json` |
| `RB_SUPABASE_JWT_AUDIENCE` | `authenticated` |
| `RB_ALLOWED_ORIGINS` | `https://riftdesk.com,https://www.riftdesk.com` (and any dev URLs) |

**If you see “Supabase auth is not configured for this environment”:** add `RB_SUPABASE_URL` and `RB_SUPABASE_ANON_KEY` in Railway Variables (and the other Supabase vars above), then redeploy so the server injects them into the page.

Optional: `RB_ENABLE_AUTO_BUILDER`, `RB_ENABLE_MODEL_OBSERVATION`, `RB_SENTRY_DSN`, etc.

`PORT` is set by Railway; the app and Procfile use it automatically.

**Cards:** The app defaults to `riftbound-cards.json` in the **project root** (visible next to `app/`, `web/`). A copy is committed there so Railway and local both use it without extra env. Override with `RB_CARDS_PATH` if needed.

**Auto-builder model:** The most recent production model (**closed-beta**) is in `artifacts/`:
- `artifacts/auto_builder/` — bundle used at runtime (default `RB_AUTO_BUILDER_DIR`).
- `artifacts/auto_builder_models/` — registry with `manifest.json` and `versions/20260305T213936Z-model-closed-beta/`. Production model id: `20260305T213936Z-model-closed-beta`.

## Custom domain with Cloudflare (riftdesk.com)

### 1. Add the domain in Railway

1. Open your **Railway** project → your service → **Settings** → **Networking** / **Domains**.
2. Click **Add custom domain** (or **Generate domain** if you only have the default `.railway.app` one).
3. Add:
   - `riftdesk.com`
   - `www.riftdesk.com`
4. Railway will show the **target** for each (e.g. `your-app.up.railway.app` or a CNAME target). Copy or keep this open.

### 2. Point Cloudflare DNS at Railway

1. Log in to **Cloudflare** → select the **riftdesk.com** zone.
2. Go to **DNS** → **Records**.
3. Add or edit records:

   **Apex (riftdesk.com):**

   - **Type:** `CNAME` (or use the A record Railway shows if they give an IP).
   - **Name:** `@` (or `riftdesk.com`).
   - **Target:** the Railway CNAME target (e.g. `production-xxxx.up.railway.app`).  
     If Cloudflare says “CNAME at root is not allowed” for your plan, use Railway’s **A** record (IP) if they provide one, or use **CNAME flattening** (Cloudflare Pro) / the “proxy to CNAME” option if available.
   - **Proxy status:** Orange cloud (Proxied) or grey (DNS only). Proxied is fine and gives Cloudflare caching/DDoS in front.

   **www:**

   - **Type:** `CNAME`
   - **Name:** `www`
   - **Target:** same Railway target as above (e.g. `production-xxxx.up.railway.app`).
   - **Proxy status:** same as apex (usually Proxied).

4. **Save**. Propagation is usually quick with Cloudflare (often under a few minutes).

### 3. SSL on Cloudflare

- With **Proxied** (orange cloud), Cloudflare terminates SSL by default (Flexible / Full / Full (Strict)).
- For your app, **Full** or **Full (Strict)** is better so traffic from Cloudflare to Railway is encrypted. Railway provides a certificate for its hostname; **Full** is enough in most cases.

**Cloudflare SSL/TLS (recommended):**

1. **SSL/TLS** → **Overview** → set encryption mode to **Full** (or **Full (Strict)** if Railway’s cert is trusted).
2. Optional: **Edge Certificates** → turn **Always Use HTTPS** on so `http://riftdesk.com` redirects to `https://riftdesk.com`.

### 4. CORS (already set)

You already have `RB_ALLOWED_ORIGINS` including `https://riftdesk.com` and `https://www.riftdesk.com`; the app will allow requests from the browser for that domain.

### 5. Check

- Visit `https://riftdesk.com` and `https://www.riftdesk.com`.
- If the apex doesn’t resolve, confirm the CNAME target in Railway and that the Cloudflare record matches it; use **DNS only** (grey cloud) temporarily to rule out proxy issues.
