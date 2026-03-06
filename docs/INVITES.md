# Sending user invites with Supabase

The app uses a **closed-beta** flow: you add invites to the database and (optionally) send Supabase Auth invite emails so users can sign up with a magic link.

## 1. Get the Supabase service role key

- Open [Supabase Dashboard](https://supabase.com/dashboard) → your project.
- Go to **Settings** → **API**.
- Under **Project API keys**, copy the **`service_role`** key (secret). It is a long JWT string.  
  ⚠️ **Never** commit this key or expose it to the frontend. Use it only in server-side scripts or env vars.

**Important:** The invite endpoint requires the **service_role** secret, not the **publishable** key (`sb_publishable_xxx`). The publishable key replaces the anon key for client-side auth only. If you get **401 Unauthorized** or "valid Bearer token", you are likely using the publishable key in `RB_SUPABASE_SERVICE_ROLE_KEY`; switch to the actual **service_role** key from the same API settings page.

## 2. Set the environment variable

When running the invite script, the script must have access to the service role key. Use either:

- **`RB_SUPABASE_SERVICE_ROLE_KEY`** (preferred), or  
- **`SUPABASE_SERVICE_ROLE_KEY`**

Examples:

- **Local (PowerShell):**  
  `$env:RB_SUPABASE_SERVICE_ROLE_KEY = "your-service-role-key-here"`
- **Local (.env):**  
  Add `RB_SUPABASE_SERVICE_ROLE_KEY=your-service-role-key-here` to `.env` (and keep `.env` in `.gitignore`).
- **Railway:**  
  Do **not** add the service role key to Railway unless you run the invite script there. Prefer running the script locally with your `.env` so the secret stays off the server.

You also need **`RB_SUPABASE_URL`** (your project URL, e.g. `https://xxxx.supabase.co`). The app config already uses this for auth; the invite script reads it from the same config.

## 3. Run the invite script

From the **repository root** (parent of `riftbound-deck-platform-v2`) or from `riftbound-deck-platform-v2` with `PYTHONPATH` set so `app` is importable:

```bash
# From repo root (Riftbound Test), with .env loaded:
python riftbound-deck-platform-v2/scripts/seed_beta_invites.py user@example.com --role user --send-supabase-invites
```

Options:

| Option | Description |
|--------|-------------|
| `email(s)` | One or more email addresses to invite. |
| `--emails-file PATH` | Text file with one email per line (UTF-8). |
| `--role user \| admin` | Role stored in `beta_invites` (default: `user`). |
| `--status invited \| accepted \| revoked` | Status to set (default: `invited`). |
| **`--send-supabase-invites`** | **Required to send Supabase invite emails.** Without this, the script only seeds the DB. |
| `--redirect-to URL` | Redirect URL in the invite email (e.g. `https://riftdesk.com` or `https://riftdesk.com/`). |

Examples:

```bash
# One email, send Supabase invite, redirect to production:
python riftbound-deck-platform-v2/scripts/seed_beta_invites.py friend@example.com --send-supabase-invites --redirect-to https://riftdesk.com

# Multiple emails from a file, admin role:
python riftbound-deck-platform-v2/scripts/seed_beta_invites.py --emails-file invites.txt --role admin --send-supabase-invites --redirect-to https://riftdesk.com
```

The script will:

1. **Seed** each email into `beta_invites` (Postgres or SQLite, depending on `RB_STORAGE_BACKEND` / `RB_DATABASE_URL`).
2. If `--send-supabase-invites` is set, call Supabase **Auth** `POST /auth/v1/invite` for each email so Supabase sends the invite email.

## 4. Supabase Auth settings

- **Authentication** → **URL Configuration**: set **Site URL** (e.g. `https://riftdesk.com`) and add **Redirect URLs** (e.g. `https://riftdesk.com/**`) so the invite link works.
- **Authentication** → **Email Templates**: you can edit the “Invite user” template if you want to customize the email body. Default is fine for most cases.

## 5. After the user accepts

When the user clicks the link in the invite email, Supabase creates the user and they sign in. Your app’s **bootstrap** flow (`/api/me/bootstrap`) checks `beta_invites` and creates or updates the user profile. Ensure the frontend calls bootstrap after sign-in so the user gets a profile and the invite is marked accepted.

## Troubleshooting: "Error sending invite email" (HTTP 500)

If the script seeds the DB but fails with **HTTP 500** and `"Error sending invite email"`, Supabase accepted the invite but **could not send the email**. Fix this in Supabase, not in the script:

1. **Supabase Dashboard** → **Project Settings** → **Auth** → **SMTP Settings**.
2. **Enable Custom SMTP** and set:
   - **Sender email** – must be an address on a domain you own (e.g. `noreply@yourdomain.com`).
   - **Host** – `smtp.resend.com` (for Resend).
   - **Port** – `465` (SSL) or `587` (TLS).
   - **Username** – `resend`.
   - **Password** – your Resend **API key** (from Resend dashboard → API Keys).
3. In **Resend**: add and verify the domain for the sender email (Resend → Domains). Until the domain is verified, Resend may reject sends and Supabase will return 500.

After saving SMTP in Supabase, run the invite script again.

## Summary checklist

- [ ] Service role key from Supabase Dashboard → Settings → API.
- [ ] `RB_SUPABASE_SERVICE_ROLE_KEY` (or `SUPABASE_SERVICE_ROLE_KEY`) set when running the script.
- [ ] `RB_SUPABASE_URL` set (and `RB_DATABASE_URL` if using Postgres for `beta_invites`).
- [ ] Run script with `--send-supabase-invites` and `--redirect-to https://riftdesk.com` (or your app URL).
- [ ] Supabase Auth URL Configuration has your site and redirect URLs.
