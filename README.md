# Riftbound Deck Platform

This is a local Windows app for building Riftbound decks, checking legality, tracking your collection, browsing deck ideas, and using the Guided Deck Wizard to replace cards you do not own.

You do not need to know Git to run it.

## What You Need

- A Windows PC
- Python 3.11 or newer
- This project folder
- An internet connection for the first install step

## Step 1: Install Python

1. Go to https://www.python.org/downloads/windows/
2. Download the latest Python 3 installer.
3. Open the installer.
4. Very important: check the box that says `Add python.exe to PATH`.
5. Click `Install Now`.
6. When it finishes, close the installer.

To check that Python installed:

1. Press `Windows key`.
2. Type `PowerShell`.
3. Open `Windows PowerShell`.
4. Type this and press Enter:

```powershell
python --version
```

If you see a Python version number, you are ready.

## Step 2: Get The Project Folder

If someone sent you a `.zip` file:

1. Right-click the `.zip` file.
2. Click `Extract All...`.
3. Pick a location you can find again, such as `Documents`.
4. Open the extracted folder.

If you are downloading from GitHub:

1. Open the project page in your browser.
2. Click the green `Code` button.
3. Click `Download ZIP`.
4. Extract the ZIP file.

After extracting, you should have a folder named something like:

```text
riftbound-deck-platform-v2
```

## Step 3: Open PowerShell In The Project Folder

1. Open the `riftbound-deck-platform-v2` folder.
2. Click the address bar at the top of File Explorer.
3. Type `powershell`.
4. Press Enter.

A PowerShell window should open already pointed at the project folder.

You can confirm you are in the right place by running:

```powershell
dir
```

You should see files like `run.py`, `requirements.txt`, and `README.md`.

## Step 4: Create A Local Python Environment

In the PowerShell window, run:

```powershell
python -m venv .venv
```

Then turn it on:

```powershell
.\.venv\Scripts\Activate.ps1
```

If Windows blocks that command, run this once:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Then try again:

```powershell
.\.venv\Scripts\Activate.ps1
```

When it works, your prompt will usually start with `(.venv)`.

## Step 5: Install The App Requirements

Run this:

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

This can take a few minutes the first time.

## Step 6: Start The App

Run:

```powershell
python run.py
```

Wait until you see a message that includes:

```text
http://127.0.0.1:8010
```

Leave this PowerShell window open while you use the app.

## Step 7: Open The App

Open your browser and go to:

```text
http://127.0.0.1:8010
```

The app is running only on your computer. Other people cannot use it unless you deploy it somewhere else.

## How To Stop The App

Go back to the PowerShell window that is running the app.

Press:

```text
Ctrl + C
```

If it asks whether to terminate the batch job, type:

```text
Y
```

Then press Enter.

## How To Start It Again Later

1. Open the project folder.
2. Click the address bar.
3. Type `powershell`.
4. Press Enter.
5. Run:

```powershell
.\.venv\Scripts\Activate.ps1
python run.py
```

Then open:

```text
http://127.0.0.1:8010
```

## Basic Use

- Use `Build` to create or edit a deck.
- Use `Explore` to browse deck ideas.
- Use `Bring to Wizard` from Explore or Builder to move a deck into the Guided Deck Wizard.
- In the Wizard, mark cards you do not own, then click `Refine for my collection`.
- Use `Cards` to manage your collection.
- Use `Save Deck` to keep a deck in your local library.

## If Something Goes Wrong

### `python` is not recognized

Python was not added to PATH.

Re-run the Python installer and make sure `Add python.exe to PATH` is checked.

### PowerShell will not activate `.venv`

Run:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
.\.venv\Scripts\Activate.ps1
```

### Port 8010 is already in use

Something else is already using the app's default port.

Close other PowerShell windows running this app, then try:

```powershell
python run.py
```

### The browser says the site cannot be reached

Make sure the PowerShell window running `python run.py` is still open.

Then refresh:

```text
http://127.0.0.1:8010
```

## Optional: Run The Tests

This is not required to use the app, but it helps confirm everything is healthy:

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest
```

