from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from run import load_dotenv_defaults

from app.core.config import load_config
from app.infra.storage import SqliteStorage


def build_storage():
    config = load_config()
    if config.storage_backend == "postgres":
        from app.infra.postgres_storage import PostgresStorage

        storage = PostgresStorage(config.database_url)
    else:
        storage = SqliteStorage(config.db_path)
    storage.init_schema()
    return storage, config


def iter_emails(args: argparse.Namespace) -> Iterable[str]:
    seen: set[str] = set()
    for raw in list(args.emails or []):
        email = str(raw or "").strip().lower()
        if email and email not in seen:
            seen.add(email)
            yield email
    if not args.emails_file:
        return
    for raw in Path(args.emails_file).read_text(encoding="utf-8").splitlines():
        email = str(raw or "").strip().lower()
        if email and email not in seen:
            seen.add(email)
            yield email


def send_supabase_invite(*, supabase_url: str, service_role_key: str, email: str, redirect_to: str = "") -> None:
    payload = {"email": email}
    if redirect_to:
        payload["redirect_to"] = redirect_to
    request = Request(
        url=f"{supabase_url.rstrip('/')}/auth/v1/invite",
        method="POST",
        headers={
            "apikey": service_role_key,
            "Authorization": f"Bearer {service_role_key}",
            "Content-Type": "application/json",
        },
        data=json.dumps(payload).encode("utf-8"),
    )
    try:
        with urlopen(request, timeout=20) as response:
            if int(response.status) // 100 != 2:
                raise RuntimeError(f"Invite request failed for {email}: HTTP {response.status}")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        msg = f"Invite request failed for {email}: HTTP {exc.code} {detail}"
        if exc.code == 500 and "invite email" in detail.lower():
            msg += "\n(Usually means Supabase could not send the email: check Project Settings → Auth → SMTP Settings and your Resend domain/API key.)"
        raise RuntimeError(msg) from exc
    except URLError as exc:
        raise RuntimeError(f"Invite request failed for {email}: {exc}") from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed beta invites into the Riftbound closed-beta database.")
    parser.add_argument("emails", nargs="*", help="Email addresses to invite.")
    parser.add_argument("--emails-file", help="Optional UTF-8 text file with one email per line.")
    parser.add_argument("--role", choices=("user", "admin"), default="user", help="Role to assign in beta_invites.")
    parser.add_argument("--status", choices=("invited", "accepted", "revoked"), default="invited", help="Invite status to store.")
    parser.add_argument("--send-supabase-invites", action="store_true", help="Also send Supabase invite emails using the service-role key.")
    parser.add_argument("--redirect-to", default="https://riftdesk.com", help="Redirect URL included in the Supabase invite email (default: https://riftdesk.com).")
    return parser.parse_args()


def main() -> int:
    load_dotenv_defaults(ROOT / ".env")
    args = parse_args()
    emails = list(iter_emails(args))
    if not emails:
        print("No emails supplied.")
        return 1

    storage, config = build_storage()
    service_role_key = ""
    if args.send_supabase_invites:
        service_role_key = str(
            os.getenv("RB_SUPABASE_SERVICE_ROLE_KEY")
            or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
            or ""
        ).strip()
        if not config.supabase_url or not service_role_key:
            print("Supabase invite sending requires RB_SUPABASE_URL and RB_SUPABASE_SERVICE_ROLE_KEY (or SUPABASE_SERVICE_ROLE_KEY).")
            return 1

    seeded = 0
    emailed = 0
    for email in emails:
        invite = storage.seed_beta_invite(email=email, role=args.role, status=args.status)
        seeded += 1
        print(f"seeded {invite.email} role={invite.role} status={invite.status}")
        if args.send_supabase_invites:
            send_supabase_invite(
                supabase_url=config.supabase_url,
                service_role_key=service_role_key,
                email=email,
                redirect_to=args.redirect_to,
            )
            emailed += 1
            print(f"emailed {email}")

    print(f"done: seeded={seeded} emailed={emailed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
