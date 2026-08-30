"""Who is making this request.

Authentication is a *port*, chosen once from the declared mode -- not an ``if
offline_mode`` branch inside the real verifier. v2 had exactly that branch: in offline
mode ``require_valid_token`` ignored the Authorization header entirely and seeded any
caller an admin invite, and offline mode switched itself on whenever Supabase env vars
were absent. A missing configuration silently became an authorization downgrade.

Here the mode is declared (``RB_MODE``), local mode refuses to bind anything but
loopback (see ``config``), and the hosted provider is a separate class that cannot be
reached by accident.
"""

from __future__ import annotations

import hmac
import secrets
from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol

from fastapi import Depends, HTTPException, Request, status

from ..config import Config
from ..services import LOCAL_USER_ID, Services, get_services

#: Where a public visitor's identity lives. Not a session: there is nothing to log into
#: and nothing to expire, so it is simply the name of this browser's shelf.
COOKIE_NAME = "rb_visitor"

#: A year. Long, because losing it loses a collection somebody spent an evening
#: entering, and there is no account to recover it from.
COOKIE_MAX_AGE = 365 * 24 * 60 * 60

#: Public ids are prefixed so they can never collide with the local single user, and so
#: a row's origin is legible in the database.
PUBLIC_PREFIX = "v_"


@dataclass(frozen=True)
class Identity:
    user_id: str
    display_name: str = ""


class IdentityProvider(Protocol):
    def identify(self, request: Request) -> Identity:
        ...


class LocalIdentityProvider:
    """Local mode: one implicit user, no login.

    Safe only because ``RB_MODE=local`` cannot bind a non-loopback address.
    """

    def identify(self, request: Request) -> Identity:
        return Identity(user_id=LOCAL_USER_ID, display_name="You")


def sign(value: str, secret: str) -> str:
    """``<value>.<mac>`` -- the id, and proof this server issued it.

    Signed rather than stored. The alternative, a table of issued ids, means a database
    write on every first visit from every crawler that never comes back; a MAC needs no
    storage at all and answers the only question that matters, which is whether we
    minted this id. It is not a secret and does not need to be: knowing somebody's
    visitor id is knowing which shelf is theirs, which is why the cookie is HttpOnly
    and SameSite=Lax rather than why the value is signed.
    """
    mac = hmac.new(secret.encode("utf-8"), value.encode("utf-8"), sha256).hexdigest()
    return f"{value}.{mac[:32]}"


def unsign(token: str, secret: str) -> str:
    """The id inside a cookie, or "" if it was not issued by this server."""
    value, _, mac = str(token or "").rpartition(".")
    if not value or not mac:
        return ""
    expected = sign(value, secret)
    # Constant time: a fast reject leaks how much of the MAC was right.
    return value if hmac.compare_digest(expected, token) else ""


class PublicIdentityProvider:
    """Public mode: one anonymous identity per browser, carried in a signed cookie.

    There is no login and nothing to log into. What this buys over a single shared
    account is separation: your decks and your collection are yours, and the next
    visitor gets an empty shelf rather than yours.

    What it deliberately does not buy is authentication. A visitor id is not a claim
    about *who* somebody is, only about which browser they arrived in, and nothing in
    the app treats it as more than that. Clearing cookies means starting over, which is
    the honest cost of not asking anybody to make an account.
    """

    def __init__(self, secret: str):
        self._secret = secret

    def identify(self, request: Request) -> Identity:
        existing = unsign(request.cookies.get(COOKIE_NAME, ""), self._secret)
        if existing.startswith(PUBLIC_PREFIX):
            return Identity(user_id=existing, display_name="You")
        # A new visitor. The cookie is written by the middleware on the way out, which
        # is the only place with a response to write it to.
        fresh = f"{PUBLIC_PREFIX}{secrets.token_urlsafe(16)}"
        request.state.issue_visitor_cookie = sign(fresh, self._secret)
        return Identity(user_id=fresh, display_name="You")


class HostedIdentityProvider:
    """Hosted mode: bearer token required.

    Deliberately unimplemented rather than permissive -- a hosted deployment fails
    closed until real verification is wired in.
    """

    def identify(self, request: Request) -> Identity:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=(
                "RB_MODE=hosted requires an authentication provider, which is not "
                "configured in this build. Run with RB_MODE=local."
            ),
        )


def build_identity_provider(config: Config) -> IdentityProvider:
    if config.is_local:
        return LocalIdentityProvider()
    if config.is_public:
        return PublicIdentityProvider(config.secret_key)
    return HostedIdentityProvider()


def current_identity(
    request: Request, services: Services = Depends(get_services)
) -> Identity:
    provider = getattr(request.app.state, "identity_provider", None)
    if provider is None:
        provider = build_identity_provider(services.config)
        request.app.state.identity_provider = provider
    identity = provider.identify(request)
    request.state.identity = identity
    # Every table hangs off users(user_id) by foreign key, so the row has to exist
    # before the first deck is saved. Local mode does this once at start-up; a public
    # visitor only becomes real when they turn up.
    if not services.config.is_local:
        services.db.ensure_user(identity.user_id, identity.display_name)
    return identity
