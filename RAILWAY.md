# Railway deployment

- **Region:** `europe-west4` (set in Railway project settings).
- **Start:** Railpack uses the `Procfile` or `railway.toml` (`uvicorn app.main:app --host 0.0.0.0 --port $PORT`).
- **Image size:** PyTorch is installed as **CPU-only** via `railpack.json` so the image stays under the 4 GB limit. Do not add `torch` to `requirements.txt`; it is installed in the custom install step.

## Required variables

Set these in Railway → your service → Variables (do not commit `.env`):

| Variable | Description |
|----------|-------------|
| `RB_STORAGE_BACKEND` | `postgres` |
| `RB_DATABASE_URL` | Supabase Postgres connection string (pooler) |
| `RB_SUPABASE_URL` | Supabase project URL |
| `RB_SUPABASE_ANON_KEY` | Supabase anon key |
| `RB_SUPABASE_JWKS_URL` | `https://<project>.supabase.co/auth/v1/.well-known/jwks.json` |
| `RB_SUPABASE_JWT_AUDIENCE` | `authenticated` |
| `RB_ALLOWED_ORIGINS` | `https://riftdesk.com,https://www.riftdesk.com` (and any dev URLs) |

Optional: `RB_ENABLE_AUTO_BUILDER`, `RB_ENABLE_MODEL_OBSERVATION`, `RB_SENTRY_DSN`, etc.

`PORT` is set by Railway; the app and Procfile use it automatically.

## Custom domain (riftdesk.com)

In Railway → Settings → Domains, add `riftdesk.com` and `www.riftdesk.com`, then set the CNAME (or A) records at your registrar as shown in the dashboard.
