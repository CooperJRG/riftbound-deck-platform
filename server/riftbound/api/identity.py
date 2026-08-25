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

from dataclasses import dataclass
from typing import Protocol

from fastapi import Depends, HTTPException, Request, status

from ..config import Config
from ..services import LOCAL_USER_ID, Services, get_services


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
    return LocalIdentityProvider() if config.is_local else HostedIdentityProvider()


def current_identity(
    request: Request, services: Services = Depends(get_services)
) -> Identity:
    provider = getattr(request.app.state, "identity_provider", None)
    if provider is None:
        provider = build_identity_provider(services.config)
        request.app.state.identity_provider = provider
    identity = provider.identify(request)
    request.state.identity = identity
    return identity
