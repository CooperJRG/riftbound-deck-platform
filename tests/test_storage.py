from __future__ import annotations

from pathlib import Path

from app.domain.models import DeckPayload
from app.infra.storage import SqliteStorage


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


def test_built_decks_reserve_collection_cards(tmp_path: Path) -> None:
    db_path = tmp_path / "deck-platform.db"
    storage = SqliteStorage(db_path)
    storage.init_schema()

    storage.set_collection_item(card_title="Card A", quantity=4)
    storage.set_collection_item(card_title="Card B", quantity=1)

    storage.create_deck(deck=_deck("Built", main={"Card A": 3, "Card B": 1}), name="Built", source="builder", bucket="built")
    storage.create_deck(deck=_deck("Saved", main={"Card A": 1}), name="Saved", source="meta", bucket="saved")

    in_use = storage.get_collection_in_use()
    assert in_use == {"Card A": 3, "Card B": 1}

    effective = storage.get_effective_collection()
    assert effective == {"Card A": 1}


def test_library_bucket_filtering(tmp_path: Path) -> None:
    db_path = tmp_path / "deck-platform.db"
    storage = SqliteStorage(db_path)
    storage.init_schema()

    built = storage.create_deck(deck=_deck("Built 1", main={"Card A": 1}), name="Built 1", source="builder", bucket="built")
    saved = storage.create_deck(deck=_deck("Saved 1", main={"Card A": 1}), name="Saved 1", source="meta", bucket="saved")

    built_rows = storage.list_decks(bucket="built")
    saved_rows = storage.list_decks(bucket="saved")
    assert {row.id for row in built_rows} == {built.id}
    assert {row.id for row in saved_rows} == {saved.id}
