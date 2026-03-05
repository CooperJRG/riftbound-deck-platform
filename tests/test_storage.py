from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from app.domain.models import DeckPayload
from app.infra.storage import SqliteStorage

TEST_USER_ID = str(uuid4())


def _deck(name: str, *, main: dict[str, int]) -> DeckPayload:
    return DeckPayload(
        name=name,
        source="test",
        format="constructed",
        legendTitle="Legend A",
        chosenChampionTitle="Champion A",
        main=main,
        runes={},
        battlefields=[],
        sideboard={},
    )


def _seed_user(storage: SqliteStorage, *, user_id: str = TEST_USER_ID, email: str = "storage-user@example.test") -> str:
    storage.seed_beta_invite(email=email, role="user")
    profile = storage.bootstrap_user_from_invite(user_id=user_id, email=email, display_name="Storage User")
    return profile.user_id


def test_built_decks_reserve_collection_cards(tmp_path: Path) -> None:
    db_path = tmp_path / "deck-platform.db"
    storage = SqliteStorage(db_path)
    storage.init_schema()
    user_id = _seed_user(storage)

    storage.set_collection_item(user_id=user_id, card_title="Card A", quantity=4)
    storage.set_collection_item(user_id=user_id, card_title="Card B", quantity=1)

    storage.create_deck(user_id=user_id, deck=_deck("Built", main={"Card A": 3, "Card B": 1}), name="Built", source="builder", bucket="built")
    storage.create_deck(user_id=user_id, deck=_deck("Saved", main={"Card A": 1}), name="Saved", source="meta", bucket="saved")

    in_use = storage.get_collection_in_use(user_id=user_id)
    assert in_use == {"Card A": 3, "Card B": 1}

    effective = storage.get_effective_collection(user_id=user_id)
    assert effective == {"Card A": 1}


def test_library_bucket_filtering(tmp_path: Path) -> None:
    db_path = tmp_path / "deck-platform.db"
    storage = SqliteStorage(db_path)
    storage.init_schema()
    user_id = _seed_user(storage)

    built = storage.create_deck(user_id=user_id, deck=_deck("Built 1", main={"Card A": 1}), name="Built 1", source="builder", bucket="built")
    saved = storage.create_deck(user_id=user_id, deck=_deck("Saved 1", main={"Card A": 1}), name="Saved 1", source="meta", bucket="saved")

    built_rows = storage.list_decks(user_id=user_id, bucket="built")
    saved_rows = storage.list_decks(user_id=user_id, bucket="saved")
    assert {row.id for row in built_rows} == {built.id}
    assert {row.id for row in saved_rows} == {saved.id}
