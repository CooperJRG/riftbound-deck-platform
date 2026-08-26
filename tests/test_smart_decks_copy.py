"""What the wizard says, and when it says nothing.

These read as small, and they are the difference between a wizard people finish and one
they abandon. Every case here came from walking the flow and finding it confusing:

* a round that greets you with a wall of warnings before you have touched anything;
* a card you already ruled out coming back looking like a mistake you must fix;
* a reason line that describes our bookkeeping instead of your decision;
* a count of cards you cannot find anywhere on the screen.

The visual half lives in `web/src/features/smartDecks.ts`; what is pinned here is the
text the server supplies and the knowledge that drives it, because that is what decides
whether a row is a question, a settled fact, or confirmation.

The app fixtures come from `conftest`.
"""

from __future__ import annotations

import pytest
from tests.test_smart_decks_api import first_deck_id, start_wizard


def answer(client, session_id, **payload):
    response = client.post(f"/api/smart-decks/sessions/{session_id}/answer", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def proposal(client, session_id):
    return client.get(f"/api/smart-decks/sessions/{session_id}").json()["proposal"]


# -- the opening round --------------------------------------------------------


def test_the_first_round_explains_itself_without_jargon(meta_client):
    session = start_wizard(meta_client)
    assert session["proposal"]["reason"] == "The strongest recent deck for this legend."


def test_a_deck_round_seeds_every_row_as_owned(meta_client):
    """So an untouched screen is calm.

    A deck round asks for exceptions. If rows arrived at zero the player would meet a
    page of shortfalls before doing anything, which reads as a list of problems rather
    than a question.
    """
    session = start_wizard(meta_client)
    rows = session["proposal"]["requirements"]
    assert rows
    assert all(row["have"] == row["needed"] for row in rows)


def test_a_checklist_seeds_every_unknown_row_at_zero(meta_client):
    """And the client must render those as questions, not as warnings.

    The pairing matters: a checklist row at zero is the *absence of an answer*, so
    styling it as a shortfall told twelve lies at once on a screen where nothing was
    yet wrong.
    """
    session = start_wizard(meta_client)
    session_id = session["sessionId"]
    answer(meta_client, session_id, deckId=first_deck_id(session), have={"harpoon-squad": 0})

    question = proposal(meta_client, session_id)["question"]
    assert question, "expected a direct question"
    unknown = [row for row in question["cards"] if not row["known"]]
    assert unknown
    assert all(row["have"] == 0 for row in unknown)


# -- a card the player has ruled out ------------------------------------------


def test_a_ruled_out_card_is_marked_known_when_it_comes_back(meta_client):
    """The complaint this file exists for.

    A card the player said they lack can legitimately reappear -- a later deck plays it
    too -- but it must arrive flagged as settled, so the interface can present it as
    "we will build around this" instead of repeating a question in an alarm colour.
    Without `known` the client cannot tell the two apart.
    """
    session = start_wizard(meta_client)
    session_id = session["sessionId"]
    answer(meta_client, session_id, deckId=first_deck_id(session), have={"harpoon-squad": 0})

    later = proposal(meta_client, session_id)
    rows = later.get("requirements") or (later.get("question") or {}).get("cards") or []
    reappeared = [row for row in rows if row["cardId"] == "harpoon-squad"]
    for row in reappeared:
        assert row["known"] is True, "a settled card must never look like a fresh question"
        assert row["exact"] is True
        assert row["have"] == 0


def test_a_settled_card_is_never_re_asked_on_a_checklist(meta_client):
    """A checklist is for cards we have no answer for. Asking twice reads as not
    listening, and it is the fastest way to lose somebody mid-flow."""
    session = start_wizard(meta_client)
    session_id = session["sessionId"]
    answer(meta_client, session_id, deckId=first_deck_id(session), have={"harpoon-squad": 0})

    question = proposal(meta_client, session_id)["question"]
    asked_fresh = [row["cardId"] for row in question["cards"] if not row["known"]]
    assert "harpoon-squad" not in asked_fresh


# -- the reason line ----------------------------------------------------------


def test_a_later_round_says_the_player_may_stop(meta_client):
    """Once a deck is secured the next round is optional, and must say so.

    A wizard that keeps presenting rounds without telling you that you already have
    what you came for feels endless, and endless is why people leave.
    """
    session = start_wizard(meta_client)
    session_id = session["sessionId"]
    # Own the whole deck: a floor exists immediately.
    answer(meta_client, session_id, deckId=first_deck_id(session), have={})

    later = proposal(meta_client, session_id)
    if later["phase"] == "propose":
        assert "already have a deck" in later["reason"]
        assert "stop here" in later["reason"]
    else:
        assert later["floor"] is not None


def test_the_reason_never_quotes_a_count_the_player_cannot_see(meta_client):
    """A deck round assumes you own what it does not ask about, so those cards look
    exactly like every other row. "4 cards we have not covered yet" points at something
    invisible, which makes the whole page feel less trustworthy rather than more.
    """
    session = start_wizard(meta_client)
    session_id = session["sessionId"]
    answer(meta_client, session_id, deckId=first_deck_id(session), have={})

    reason = proposal(meta_client, session_id)["reason"]
    assert "we have not covered" not in reason
    assert "we have not asked about" not in reason


@pytest.mark.parametrize("shortfall", [1, 2])
def test_the_wizard_counts_in_english(meta_client, shortfall):
    """"You still need 1 more cards" is the wizard asking for effort while sounding
    careless. It is one line of code and it is worth getting right."""
    session = start_wizard(meta_client)
    session_id = session["sessionId"]
    answer(
        meta_client, session_id,
        deckId=first_deck_id(session),
        have={"harpoon-squad": 3 - shortfall},
    )
    question = proposal(meta_client, session_id).get("question")
    if not question:
        pytest.skip("this collection needed no follow-up question")
    reason = question["reason"]
    assert "1 cards" not in reason
    if shortfall == 1:
        assert "1 more card." in reason
    else:
        assert "more cards" in reason
