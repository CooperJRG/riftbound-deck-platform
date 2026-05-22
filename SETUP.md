# Local Setup Guide

Get the Riftbound Deck Platform running on a new machine in offline mode (no Supabase account needed).

## Prerequisites

- **Python 3.13** — download from [python.org](https://www.python.org/downloads/). During install, check "Add Python to PATH".
- **Git** — download from [git-scm.com](https://git-scm.com/downloads).

## 1. Clone the repo

```powershell
git clone https://github.com/CooperJRG/riftbound-deck-platform.git
cd riftbound-deck-platform
```

## 2. Create a virtual environment (recommended)

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

> If PowerShell blocks the activation script, run: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

## 3. Install dependencies

For basic use (deck building, collection, meta browsing):

```powershell
pip install -r requirements.txt
```

For auto-builder and tests (adds PyTorch ~800 MB and pytest):

```powershell
pip install -r requirements-dev.txt
```

> **Note:** PyTorch downloads ~800 MB. Omit it if you don't need the auto-builder feature — the rest of the app works without it.

## 4. Set up the .env file

Create a `.env` file in the project root with the following content (copy-paste exactly):

```
RB_STORAGE_BACKEND=sqlite
RB_OFFLINE_MODE=1
RB_ALLOWED_ORIGINS=http://127.0.0.1:8010,http://localhost:8010
RB_ENABLE_AUTO_BUILDER=1
RB_ENABLE_MODEL_OBSERVATION=1
RB_META_AUTO_REFRESH_ENABLED=0
```

This runs the app fully locally using SQLite — no Supabase login or internet connection required.

## 5. Run the app

```powershell
python run.py
```

Then open **http://127.0.0.1:8010** in your browser.

## 6. Run tests (optional)

```powershell
python -m pytest -q
```

Requires the dev dependencies from step 3.

---

## Troubleshooting

**`python` not found** — Try `python3` instead, or reinstall Python and make sure "Add to PATH" is checked.

**`pip install` fails on psycopg[binary]** — This requires a C compiler on some systems. On Windows, install [Visual C++ Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/) and retry.

**Port already in use** — Another process is on port 8010. Either stop it, or set `RB_PORT=8011` in your `.env` and reload.

**Auto-builder tab is missing/disabled** — PyTorch isn't installed. Run `pip install -r requirements-dev.txt` to add it.

**Changes aren't showing** — The server doesn't hot-reload. Stop it (`Ctrl+C`) and restart with `python run.py`.
