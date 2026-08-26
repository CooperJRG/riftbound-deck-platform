# Riftbound Deck Builder

Build Riftbound decks, check them against the official rules, and see at a glance which
cards you can actually field.

You do not need to know Git, and you do not need to catalogue your collection before
you get value out of it.

---

## Two ways to say what you can play

Most deck builders make you record every card you own before they can help. That is a
long evening of data entry, and it goes stale the moment a new set releases.

**"Cards I don't have"** *(the easy one)* — click **I don't have this** on any card.
That card gets pushed down the rankings and flagged in your decks. Everything else stays
available, including cards from sets released after you set it up. You can also tick a
whole class in one go: *no Epics*, *no promo-only cards*, *nothing from Unleashed*.

**"My collection"** — record what you own for exact answers. More precise, more setup.

Either way, cards you lack are **de-emphasised, not banned**, so the builder always has
a legal deck to offer you. If you want the strict version — only what you could sleeve up
tonight — tick **Only what I can build now**.

---

## Running it

### What you need

- Windows, macOS or Linux
- **Python 3.11 or newer** — [python.org/downloads](https://www.python.org/downloads/).
  On Windows, tick **Add python.exe to PATH** during install.

That's the whole list. There is no machine-learning dependency, no database server, and
no account to create.

### First time

Open a terminal in the project folder and run:

```bash
python -m venv .venv
```

Turn it on — on Windows:

```powershell
.\.venv\Scripts\Activate.ps1
```

(If Windows blocks that, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once,
then try again.) On macOS or Linux:

```bash
source .venv/bin/activate
```

Install the app:

```bash
pip install -e .
```

Build the card data:

```bash
python -m riftbound.data.pipeline build --promote
```

### Every time

```bash
python -m riftbound
```

Then open **http://127.0.0.1:8020**.

Leave the terminal window open while you use it. Press `Ctrl + C` to stop.

---

## Card data

Card data is fetched from the dotgg community card API. The card list lives in a
**bundle** — a dated, checksummed snapshot with a record of where it came from. Bundles
are never edited in place, so a bad refresh can be inspected and rolled back rather than
silently becoming the truth.

To pick up a newly released set, just re-run the build — nothing in the code enumerates
known sets, so a new one needs no code change.

```bash
python -m riftbound.data.pipeline build --promote   # fetch, validate, publish
python -m riftbound.data.pipeline build      # fetch and validate, don't publish
python -m riftbound.data.pipeline list       # what's on disk
python -m riftbound.data.pipeline promote ID # publish a specific bundle
python -m riftbound.data.pipeline show       # what's live, and how healthy its sources were
```

`build` runs every source independently and refuses to publish a bundle that fails
validation — in particular, one that has *lost* a meaningful number of cards, which is
what a broken scraper looks like. Sources that fail are recorded in the bundle manifest
and visible at `/api/data/bundle`.

Where the field has moved but the rulebook may not have, a profile can *relax* a limit and
still caution about it — `sideboard_max` is 10 with an advisory at 8, so a tournament list
imports cleanly and still tells you to trim before a sanctioned event. Those show as
notices in their own "Before you play" section and never make a deck illegal.

It also reports **ban-list drift**: cards the source marks banned that your format
profile does not (or the reverse). Rules profiles in `data/rules/` remain the authority
on legality, so acting on a drift report is a deliberate edit, never automatic.

Working offline, or want to build from a known-good file? Point it at the bundled seed
export instead of the network:

```bash
python -m riftbound.data.pipeline build --promote --source data/seed/cards-export.json
```

---

## Developing

The UI is TypeScript built with Vite. For live reload:

```bash
python -m riftbound          # terminal 1 — API on :8020
cd web && npm install && npm run dev   # terminal 2 — UI on :5173 (proxies /api)
```

To produce the bundled UI that the Python server serves directly:

```bash
cd web && npm run build
```

Tests:

```bash
pip install -e ".[dev]"
python -m pytest
```

They run in about two seconds and need nothing but the source tree.

---

## How it is put together

```
server/riftbound/
  config.py          every path derived from one root; missing data is a startup error
  domain/            pure logic, no I/O
    ids.py           card_id (gameplay) vs print_id (a specific printing)
    cards.py         the catalogue
    rules.py         format profiles loaded from data/rules/*.json
    validator.py     legality, with rulebook citations on every issue
    availability.py  the two modes, resolved to one function
    deck.py          the deck model
  data/              ingest pipeline: sources -> normalise -> gate -> bundle
  infra/             SQLite, migrations, repositories
  api/               FastAPI routes, request/response schemas
web/src/             TypeScript UI (api / state / features / ui)
data/                rules profiles, card bundles, your database
tests/
```

Three rules the layout enforces:

1. **Nothing above the project root.** Every path comes from one `ROOT`; a configured
   path that escapes it is rejected at startup.
2. **`card_id` is the key.** Decks and collections never store a display name, so a card
   renamed upstream cannot orphan itself out of your deck.
3. **Rules are data.** Adding a format means adding a JSON file to `data/rules/`, and
   every legality message cites the sections it came from.

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for why each of those exists.
