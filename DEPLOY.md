# Deploying to riftdesk.com

This replaces the v2 app currently serving the domain. v2 runs on Railway
(`europe-west4`) behind Cloudflare DNS, with Supabase for Postgres and auth; v3 needs
neither Supabase service, so the cutover removes moving parts rather than adding them.

Everything below except the Railway and Cloudflare steps has been run and verified. The
Dockerfile itself has **not** been built — there is no Docker on the development machine
— though every command inside it has been run individually.

---

## What changed to make this possible

v3 shipped with two modes: `local` (one implicit user, refuses to bind anything but
loopback) and `hosted` (bearer token, deliberately unimplemented so a hosted deployment
fails closed). Pointing a domain at it would have served 501 to every request that
needed an identity — including the card browser and the deck library.

There is now a third mode, `public`:

* Every browser gets an anonymous identity in a signed, HttpOnly cookie. No login, no
  account, nothing to recover.
* Decks and collections are per-browser. Your shelf is yours; the next visitor gets an
  empty one.
* Clearing cookies starts over. That is the honest cost of not asking anyone to sign up,
  and it is why the cookie lasts a year.

`hosted` still fails closed, so this did not weaken it — it added a mode beside it.

---

## Railway service

**Build:** `railway.toml` selects the Dockerfile, so no buildpack detection is involved.
The image builds the frontend with Node 22 and serves it from Python 3.12 — the type
check runs as part of `npm run build`, so a type error fails the deploy instead of
shipping.

**Variables** (Railway → service → Variables):

| Variable | Value | Why |
|---|---|---|
| `RB_MODE` | `public` | Anonymous per-browser identities. |
| `RB_SECRET_KEY` | a long random string | Signs the identity cookie. **Set this once and never rotate it casually** — changing it invalidates every visitor's cookie, and every saved deck and collection becomes unreachable. Generate with `python -c "import secrets; print(secrets.token_urlsafe(48))"`. |
| `RB_DATA_DIR` | `/app/data` | Must stay inside `/app`; `_under_root` rejects anything that escapes the project root. |
| `RB_META_REFRESH` | `true` | Harvests the meta on a schedule. Off by default in non-local modes. |
| `RB_META_REFRESH_HOURS` | `6` | Sources publish far less often than hourly. |

`PORT` is set by Railway and read automatically.

**Volume:** in Railway → service → Settings → Volumes, add one mounted at **`/app/data`**.
This has to be done from the dashboard (or `railway volume` in the CLI) — the Dockerfile
does not and cannot declare it. An earlier version of this image had a `VOLUME
["/app/data"]` instruction; Railway's builder rejects that outright ("use Railway
Volumes instead"), which is the first thing that broke here. Without a real Railway
Volume mounted, the SQLite database is part of the container filesystem, so every
deploy silently wipes every saved deck and collection. This is the single most
important setting on this page.

---

## First boot

The entrypoint builds a card bundle if the volume has none — from upstream, falling back
to the seed committed at `data/seed/cards-export.json` if upstream is unreachable. A
stale card list beats a site that will not start. The fallback carries 769 cards against
the 948 upstream currently has, so let it reach the network if it can.

The meta snapshot is not required either, and no longer needs a live harvest to appear.
A real snapshot — currently 19,642 decks across 513 tournaments — is committed at
`data/meta-seed/` and copied into `data/meta/` by `Services.warm()` the moment the app
starts, whenever the volume has nothing promoted yet. Explore, Smart Decks and the field
guide all render from it on the very first request; nothing waits on a harvest.

This exists because the harvest is not cheap: a cold Riftools pull is one request per
decklist, around 14,700 of them, roughly 25 minutes, and it caches to `var/`, which is
**not** on the volume — so without a seed, every deploy would restart that 25-minute
cold start from zero. Storage for the snapshot itself is cheap (36 MB, baked into the
image), so committing it is the fix rather than mounting a second volume for the cache.

Once `RB_META_REFRESH=true` runs its first live harvest, that harvest's result is
promoted over the seed in the ordinary way — the seed is a starting point, not a
ceiling, and `seed_meta_if_missing` never overwrites a snapshot that is already
promoted. **Refresh the seed occasionally**, or it drifts further from the live archive
with every day that passes:

```bash
cp data/meta/$(cat data/meta/current.txt)/{manifest,meta}.json data/meta-seed/
git add data/meta-seed && git commit -m "Refresh the committed meta seed"
```

---

## Cutting over the domain

1. Deploy the service and confirm it on the generated `*.up.railway.app` URL first.
   Check `/api/health` reports `"mode": "public"` and a non-zero `cardCount`, then load
   a deep link such as `/explore` and a share link to confirm the SPA fallback works.
2. In Railway → service → Settings → Networking, add `riftdesk.com` and
   `www.riftdesk.com`, and copy the CNAME target it shows.
3. In Cloudflare → the `riftdesk.com` zone → DNS, repoint the apex and `www` records at
   the new target. Both were pointing at the v2 service.
4. Keep the v2 service running until the new one has served traffic for a day. Rolling
   back is then a DNS change rather than a redeploy.

I cannot perform steps 2–4: they need Railway and Cloudflare credentials, which I will
not handle. They are all clicks in those two dashboards.

---

## What does not come across

**v2's user data stays in Supabase.** Anyone who saved a deck on the old riftdesk.com
will not find it on the new one — different storage, and v3 has no accounts to attach it
to. Options, in order of effort: accept it and say so on the site; export the Supabase
decks and offer them as share links; or implement real accounts (`hosted` mode) and
migrate. Decide before the DNS change, because after it the old site is unreachable to
the people who would notice.

**Branding.** The product, page metadata, and domain all use *RiftDesk*. The old
*Bound Atlas* browser preferences are read once as a compatibility fallback, so an
existing visitor keeps their light/dark choice through the rebrand.

---

## Running the image locally

```
docker build -t riftdesk .
docker run --rm -p 8020:8020 \
  -e RB_MODE=public \
  -e RB_SECRET_KEY=dev-only-not-a-real-secret \
  -v riftdesk-data:/app/data \
  riftdesk
```

Same image as production, which is most of the reason it is a Dockerfile.
