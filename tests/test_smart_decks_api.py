"""Smart Decks over HTTP.

The engine is proven by `test_smart_decks.py` and the acceptance run; what these cover
is the boundary, where the interesting failures are different: knowledge surviving a
round trip, an answer meaning the same thing after being written to SQLite and read
back, and the two write actions at the end staying opt-in.

The app fixtures (`client`, `meta_client`) come from `conftest`.
"""

from __future__ import annotations

LEGEND_ID = "vi-piltover-enforcer"


def start_wizard(client, legend_id=LEGEND_ID):
    response = client.post("/api/smart-decks/sessions", json={"legendId": legend_id})
    assert response.status_code == 201, response.text
    return response.json()


def first_deck_id(session):
    return session["proposal"]["deck"]["deckId"]


# -- legends ------------------------------------------------------------------


def test_the_wizard_needs_meta_decks_and_says_so(client):
    """With no snapshot there is nothing to propose, and that is not a crash."""
    response = client.post("/api/smart-decks/sessions", json={"legendId": LEGEND_ID})
    assert response.status_code == 404
    assert "no published decks" in response.json()["detail"].lower()


def test_legends_are_ranked_and_never_filtered_by_collection(meta_client):
    """Familiarity is a hint. Hiding legends would rebuild the barrier we removed."""
    body = meta_client.get("/api/smart-decks/legends").json()
    assert body
    entry = next(row for row in body if row["legendId"] == LEGEND_ID)
    assert entry["deckCount"] >= 1
    assert entry["name"] == "Vi - Piltover Enforcer"
    assert 0.0 <= entry["familiarity"] <= 1.0


# -- a round ------------------------------------------------------------------


def test_a_session_opens_with_a_deck_and_a_full_requirement_list(meta_client):
    session = start_wizard(meta_client)
    proposal = session["proposal"]
    assert proposal["phase"] == "propose"
    assert proposal["deck"] is not None
    rows = proposal["requirements"]
    # Every zone is represented, because a deck you cannot field is not a deck.
    assert {row["zone"] for row in rows} >= {"legend", "main", "runes", "battlefields"}
    assert any(row["cardId"] == "fury-rune" and row["needed"] == 12 for row in rows)


def test_a_requirement_row_defaults_to_having_the_cards(meta_client):
    """The common answer is yes, so the common answer should cost no clicks.

    Runes are the exception and are settled rather than merely defaulted: nobody is
    short of the resource base, so the row is marked known and the player is not asked
    to confirm the one answer that is always yes.
    """
    session = start_wizard(meta_client)
    for row in session["proposal"]["requirements"]:
        assert row["have"] == row["needed"]
        assert row["known"] is (row["zone"] == "runes")


def test_answers_survive_a_round_trip(meta_client):
    """The answers are the expensive part of a session; a closed tab must not cost them."""
    session = start_wizard(meta_client)
    answered = meta_client.post(
        f"/api/smart-decks/sessions/{session['sessionId']}/answer",
        json={"deckId": first_deck_id(session), "have": {"harpoon-squad": 1}},
    )
    assert answered.status_code == 200, answered.text

    reloaded = meta_client.get(f"/api/smart-decks/sessions/{session['sessionId']}").json()
    assert reloaded["rounds"] == 1
    assert reloaded["knownCards"] > 0


def test_a_partial_count_is_recorded_as_a_shortfall(meta_client):
    """Having 2 of a 3-of is the case the wizard exists for, not an edge case.

    The proof is in the arithmetic: reporting 2 of 3 must leave the player one card
    short, not three. Treating a partial answer as "missing entirely" is the mistake
    this flags, and it would show up here as "Short by 3".
    """
    session = start_wizard(meta_client)
    session_id = session["sessionId"]
    meta_client.post(
        f"/api/smart-decks/sessions/{session_id}/answer",
        json={"deckId": first_deck_id(session), "have": {"harpoon-squad": 2}},
    )
    body = meta_client.get(f"/api/smart-decks/sessions/{session_id}").json()
    assert body["proposal"]["feasibility"] == "Short by 1 more main."
    assert body["proposal"]["question"]["reason"].startswith("You still need 1 more card.")


def test_saying_you_have_them_all_does_not_cap_your_collection(meta_client):
    """The knowledge bug, guarded at the API boundary.

    Twelve runes reported as "yes, I have the twelve this deck wants" must not be
    written down as exactly twelve and no more, or a later deck asking for more finds a
    player short who is not.
    """
    session = start_wizard(meta_client)
    session_id = session["sessionId"]
    meta_client.post(
        f"/api/smart-decks/sessions/{session_id}/answer",
        json={"deckId": first_deck_id(session), "have": {"fury-rune": 12}},
    )
    body = meta_client.get(f"/api/smart-decks/sessions/{session_id}").json()
    assert not [g for g in body["proposal"]["gaps"] if g["cardId"] == "fury-rune"]


def test_a_checklist_does_not_answer_itself(meta_client):
    """The mirror of the false negative, and the one a truthful harness cannot catch.

    A deck round shows a list somebody really played and asks what you are short of, so
    "I have these" is the right default. A checklist shows cards nobody has been asked
    about and reads "which of these do you own" -- defaulting those to owned answers the
    question on the player's behalf, and hands anyone who clicks straight through a deck
    they cannot build.
    """
    session = start_wizard(meta_client)
    session_id = session["sessionId"]
    for row in session["proposal"]["requirements"]:
        assert row["have"] == row["needed"], "a deck round assumes you have its cards"

    # Drive the session to a checklist by coming up short.
    meta_client.post(
        f"/api/smart-decks/sessions/{session_id}/answer",
        json={"deckId": first_deck_id(session), "have": {"harpoon-squad": 0}},
    )
    body = meta_client.get(f"/api/smart-decks/sessions/{session_id}").json()
    question = body["proposal"]["question"]
    assert question, "expected a direct question once the decks ran out"
    assert question["cards"], "a question with no cards is not a question"
    unknown = [row for row in question["cards"] if not row["known"]]
    assert unknown, "expected the question to cover cards we have not asked about"
    for row in unknown:
        assert row["have"] == 0, f"{row['cardId']} was answered for the player"
    # A card an earlier round did establish keeps what we learned; that is not a guess.
    for row in question["cards"]:
        if row["known"]:
            assert row["have"] > 0


def test_a_checklist_answer_must_say_what_it_asked(meta_client):
    """Unticked means none; absent means unasked. Conflating them is the false negative."""
    session = start_wizard(meta_client)
    response = meta_client.post(
        f"/api/smart-decks/sessions/{session['sessionId']}/answer", json={"have": {}}
    )
    assert response.status_code == 400
    assert "unticked" in response.json()["detail"]


def test_a_deck_from_another_legend_is_refused(meta_client):
    session = start_wizard(meta_client)
    response = meta_client.post(
        f"/api/smart-decks/sessions/{session['sessionId']}/answer",
        json={"deckId": "not-a-real-deck", "have": {}},
    )
    assert response.status_code == 400


# -- finishing ----------------------------------------------------------------


def test_a_finished_session_can_be_accepted_into_the_library(meta_client):
    """The floor is a real deck, so accepting it produces a real library entry."""
    session = start_wizard(meta_client)
    session_id = session["sessionId"]
    # An empty `have` means "I have everything this deck asked for".
    meta_client.post(
        f"/api/smart-decks/sessions/{session_id}/answer",
        json={"deckId": first_deck_id(session), "have": {}},
    )
    accepted = meta_client.post(
        f"/api/smart-decks/sessions/{session_id}/accept", json={"which": "floor"}
    )
    assert accepted.status_code == 200, accepted.text
    saved_deck_id = accepted.json()["savedDeckId"]
    assert saved_deck_id

    stored = meta_client.get(f"/api/decks/{saved_deck_id}")
    assert stored.status_code == 200
    assert stored.json()["deck"]["legendId"] == LEGEND_ID


def test_accepting_a_deck_that_does_not_exist_yet_is_a_conflict_not_a_crash(meta_client):
    session = start_wizard(meta_client)
    response = meta_client.post(
        f"/api/smart-decks/sessions/{session['sessionId']}/accept", json={"which": "free"}
    )
    assert response.status_code == 409


def test_the_collection_is_never_written_without_being_asked(meta_client):
    """Answering to get a deck is not the same as recording a permanent fact.

    Checked against the collection itself rather than the availability view: that view
    reports the profile's lens, which is empty in the default open mode whether or not
    anything was written, so it cannot tell the two apart.
    """
    from riftbound.services import get_services

    collections = get_services().collections
    session = start_wizard(meta_client)
    session_id = session["sessionId"]
    meta_client.post(
        f"/api/smart-decks/sessions/{session_id}/answer",
        json={"deckId": first_deck_id(session), "have": {"harpoon-squad": 2}},
    )
    assert collections.total_copies(user_id="local") == 0, "answering wrote nothing"

    written = meta_client.post(
        f"/api/smart-decks/sessions/{session_id}/save-collection", json={}
    )
    assert written.status_code == 200, written.text
    assert written.json()["cardsWritten"] == 1
    assert written.json()["copiesWritten"] == 2
    assert collections.total_copies(user_id="local") == 2


def test_write_back_counts_only_what_the_collection_can_show_back(meta_client):
    """A card answered as zero is recorded, but it is not a card added.

    Reporting "1 card written" and then showing an empty collection is a small lie, and
    the kind that makes a player stop believing the rest of the numbers.
    """
    session = start_wizard(meta_client)
    session_id = session["sessionId"]
    meta_client.post(
        f"/api/smart-decks/sessions/{session_id}/answer",
        json={"deckId": first_deck_id(session), "have": {"harpoon-squad": 0}},
    )
    result = meta_client.post(
        f"/api/smart-decks/sessions/{session_id}/save-collection", json={}
    ).json()
    assert result["cardsWritten"] == 0
    assert result["cardsCleared"] == 1


def test_write_back_reports_the_lower_bounds_it_skipped(meta_client):
    """"At least six" is not a count, and writing it as one understates a player."""
    session = start_wizard(meta_client)
    session_id = session["sessionId"]
    meta_client.post(
        f"/api/smart-decks/sessions/{session_id}/answer",
        json={"deckId": first_deck_id(session), "have": {"fury-rune": 12}},
    )
    result = meta_client.post(
        f"/api/smart-decks/sessions/{session_id}/save-collection", json={}
    ).json()
    assert result["skippedLowerBounds"] >= 1


# -- bans ---------------------------------------------------------------------


def test_a_proposal_carries_ban_warnings(meta_client):
    """Told, not enforced -- we do not know which format they are playing."""
    session = start_wizard(meta_client)
    assert "banNotices" in session["proposal"]


def test_a_banned_card_the_wizard_left_out_explains_itself(meta_client, monkeypatch):
    """Otherwise the player compares against the original and assumes we slipped up."""
    from riftbound.services import get_services

    catalog = get_services().catalog
    card = catalog.get("harpoon-squad")
    object.__setattr__(card, "banned_upstream", True)
    try:
        session = start_wizard(meta_client)
        notices = session["proposal"]["banNotices"]
        entry = next((n for n in notices if n["cardId"] == "harpoon-squad"), None)
        assert entry is not None
        assert entry["source"] == "upstream"
        assert entry["enforced"] is False
        assert "check your event" in entry["message"]
    finally:
        object.__setattr__(card, "banned_upstream", False)


# -- housekeeping -------------------------------------------------------------


def test_a_session_can_be_abandoned(meta_client):
    session = start_wizard(meta_client)
    session_id = session["sessionId"]
    assert meta_client.delete(f"/api/smart-decks/sessions/{session_id}").status_code == 204
    assert meta_client.get(f"/api/smart-decks/sessions/{session_id}").status_code == 404


def test_sessions_are_listed_so_a_run_can_be_resumed(meta_client):
    start_wizard(meta_client)
    body = meta_client.get("/api/smart-decks/sessions").json()
    assert len(body) == 1
    assert body[0]["legendId"] == LEGEND_ID


def test_one_users_session_is_not_another_users(meta_client):
    """Local mode has a single user, but the query is scoped from the first migration."""
    session = start_wizard(meta_client)
    from riftbound.services import get_services

    services = get_services()
    assert services.smart_decks.get(session["sessionId"], user_id="someone-else") is None


# -- the wizard chooses, and shows its working ---------------------------------


def test_a_proposal_carries_both_scores(meta_client):
    """The player is owed the numbers the app decided on."""
    session = meta_client.post(
        "/api/smart-decks/sessions", json={"legendId": "vi-piltover-enforcer"}
    ).json()
    proposal = session["proposal"]
    score = proposal["deckScore"]
    assert score is not None
    assert set(score) >= {"meta", "legend", "coverage", "scored", "summary", "disclaimer"}
    assert score["summary"]


def test_the_wizard_picks_a_repair_rather_than_asking(meta_client):
    """It used to render both and leave the player to arbitrate between two lists they
    had never seen played. `chosen` names the one to show."""
    session = meta_client.post(
        "/api/smart-decks/sessions", json={"legendId": "vi-piltover-enforcer"}
    ).json()
    proposal = session["proposal"]
    assert proposal["chosen"] in ("", "conservative", "free")
    if proposal["chosen"]:
        picked = proposal[proposal["chosen"]]
        assert picked is not None, "chosen must name a repair that is actually present"
        assert picked["score"] is not None


def test_a_card_can_be_declined_and_taken_back(meta_client):
    """The endpoint that was shipped broken once: nothing exercised the writer, so a
    call to a method the Database does not have passed every test and 500'd live."""
    session = meta_client.post(
        "/api/smart-decks/sessions", json={"legendId": "vi-piltover-enforcer"}
    ).json()
    session_id = session["sessionId"]
    assert session["declined"] == []

    card = session["proposal"]["requirements"][0]["cardId"]
    declined = meta_client.post(
        f"/api/smart-decks/sessions/{session_id}/decline", json={"cardIds": [card]}
    ).json()
    assert [row["cardId"] for row in declined["declined"]] == [card]
    assert declined["declined"][0]["name"], "a decline has to be nameable to be shown"

    # The whole set, not a delta -- so taking one back is the same call.
    restored = meta_client.post(
        f"/api/smart-decks/sessions/{session_id}/decline", json={"cardIds": []}
    ).json()
    assert restored["declined"] == []


def test_a_decline_survives_reloading_the_session(meta_client):
    session = meta_client.post(
        "/api/smart-decks/sessions", json={"legendId": "vi-piltover-enforcer"}
    ).json()
    session_id = session["sessionId"]
    card = session["proposal"]["requirements"][0]["cardId"]
    meta_client.post(
        f"/api/smart-decks/sessions/{session_id}/decline", json={"cardIds": [card]}
    )
    reloaded = meta_client.get(f"/api/smart-decks/sessions/{session_id}").json()
    assert [row["cardId"] for row in reloaded["declined"]] == [card]


def test_the_floor_arrives_with_cards_to_show(meta_client):
    """The finish screen shows the deck; a payload of card ids is not one."""
    session = meta_client.post(
        "/api/smart-decks/sessions", json={"legendId": "vi-piltover-enforcer"}
    ).json()
    floor = session["proposal"].get("floor")
    if floor is not None:
        assert floor["cards"], "a floor must be renderable, not just a card-id map"
        assert all(row["name"] for row in floor["cards"])
