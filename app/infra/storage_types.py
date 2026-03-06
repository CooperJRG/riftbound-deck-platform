from __future__ import annotations

from pathlib import Path
from typing import Protocol

from app.domain.models import BetaInviteSummary, DeckLibraryRow, DeckPayload, UserProfileSummary


class StorageProtocol(Protocol):
    @property
    def db_path(self) -> Path | None: ...

    def init_schema(self) -> None: ...

    def schema_version(self) -> int: ...

    def schema_status(self) -> dict[str, object]: ...

    def get_collection(self, *, user_id: str) -> dict[str, int]: ...

    def set_collection_item(self, *, user_id: str, card_title: str, quantity: int) -> None: ...

    def upsert_collection(self, user_id: str, cards_map: dict[str, int], *, replace_existing: bool = False) -> None: ...

    def clear_collection(self, *, user_id: str) -> None: ...

    def get_built_cards_in_use(self, *, user_id: str) -> dict[str, int]: ...

    def get_collection_in_use(self, *, user_id: str) -> dict[str, int]: ...

    def get_effective_collection(self, *, user_id: str) -> dict[str, int]: ...

    def list_decks(self, *, user_id: str, bucket: str | None = None, query: str = "") -> list[DeckLibraryRow]: ...

    def list_public_decks(
        self,
        *,
        viewer_user_id: str,
        query: str = "",
        format_name: str | None = None,
        limit: int = 60,
        offset: int = 0,
        sort_by: str = "updated",
    ) -> list[DeckLibraryRow]: ...

    def get_deck(self, *, user_id: str, deck_id: str) -> DeckLibraryRow | None: ...

    def get_public_deck(self, *, viewer_user_id: str, deck_id: str) -> DeckLibraryRow | None: ...

    def create_deck(
        self,
        *,
        user_id: str,
        deck: DeckPayload,
        name: str,
        source: str,
        bucket: str | None = None,
        visibility: str | None = None,
    ) -> DeckLibraryRow: ...

    def update_deck(
        self,
        deck_id: str,
        *,
        user_id: str,
        deck: DeckPayload,
        name: str | None,
        source: str | None,
        bucket: str | None = None,
        visibility: str | None = None,
    ) -> DeckLibraryRow | None: ...

    def set_deck_bucket(self, *, user_id: str, deck_id: str, bucket: str) -> DeckLibraryRow | None: ...

    def delete_deck(self, *, user_id: str, deck_id: str) -> bool: ...

    def get_profile(self, *, user_id: str) -> UserProfileSummary | None: ...

    def get_profile_by_email(self, *, email: str) -> UserProfileSummary | None: ...

    def seed_beta_invite(self, *, email: str, role: str = "user", status: str = "invited") -> BetaInviteSummary: ...

    def get_beta_invite(self, *, email: str) -> BetaInviteSummary | None: ...

    def bootstrap_user_from_invite(self, *, user_id: str, email: str, display_name: str) -> UserProfileSummary: ...

    def update_display_name(self, *, user_id: str, display_name: str) -> UserProfileSummary: ...

    def like_deck(self, *, user_id: str, deck_id: str) -> None: ...

    def unlike_deck(self, *, user_id: str, deck_id: str) -> None: ...
