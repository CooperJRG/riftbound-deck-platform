"""API tests.

The fixture builds a temporary data root, writes a small bundle, and starts the app.
It takes milliseconds and imports no machine-learning library -- contrast v2, where
this fixture trained an NMF + MoE model and a numerical bug in it failed sixteen
tests covering auth, decks and collections.
"""

from __future__ import annotations

import pytest


def deck_payload(**overrides):
    main = {"vi-destructive": 3, "brazen-buccaneer": 3, "harpoon-squad": 3,
            "singular-relic": 1, "showcase-only": 3}
    main.update({f"filler-{i:02d}": 3 for i in range(1, 10)})
    payload = {
        "name": "API Deck", "format": "constructed",
        "legendId": "vi-piltover-enforcer", "championId": "vi-destructive",
        "main": main, "runes": {"fury-rune": 12},
        "battlefields": ["the-arena", "the-forge", "the-spire"], "sideboard": {},
    }
    payload.update(overrides)
    return payload


# -- meta ---------------------------------------------------------------------


def test_health_reports_the_bundle_and_migrations(client):
    body = client.get("/api/health").json()
    assert body["ok"] is True
    assert body["mode"] == "local"
    assert body["cardCount"] > 0
    assert "001_initial.sql" in body["migrations"]


def test_formats_expose_constraints_and_resolved_bans(client):
    formats = client.get("/api/formats").json()
    constructed = next(f for f in formats if f["format"] == "constructed")
    # Constraint keys pass through exactly as authored in the rules profile — they are
    # data, not API fields, and they key the profile's rule_refs. Renaming them would
    # break that correspondence.
    assert constructed["constraints"]["main_deck_size_exact"] == 40
    assert constructed["bannedCardIds"] == ["banned-blade"], "ban names resolved to ids"


def test_bundle_endpoint_reports_provenance(client):
    body = client.get("/api/data/bundle").json()
    assert body["bundleId"]
    assert body["cardCount"] > 0


# -- cards --------------------------------------------------------------------


def test_cards_are_listed_with_availability(client):
    body = client.get("/api/cards").json()
    assert body["total"] > 0
    first = body["cards"][0]
    assert first["weight"] == 1.0
    assert "cardId" in first["card"]


def test_card_search_matches_names(client):
    body = client.get("/api/cards", params={"q": "buccaneer"}).json()
    assert [c["card"]["cardId"] for c in body["cards"]] == ["brazen-buccaneer"]


def test_card_filters_combine(client):
    body = client.get("/api/cards", params={"cardType": "Battlefield"}).json()
    assert body["total"] == 3


def test_facets_come_from_the_bundle(client):
    facets = client.get("/api/cards/facets").json()
    assert "Battlefield" in facets["cardTypes"]
    assert "Fury" in facets["domains"]


def test_unknown_card_is_404(client):
    assert client.get("/api/cards/no-such-card").status_code == 404


# -- deck validation ----------------------------------------------------------


def test_a_legal_deck_validates(client):
    body = client.post("/api/decks/validate", json=deck_payload()).json()
    assert body["legal"] is True, body["issues"]
    assert body["mainTotal"] == 40


def test_validation_issues_cite_the_rulebook(client):
    payload = deck_payload()
    payload["main"]["filler-01"] = 1
    body = client.post("/api/decks/validate", json=payload).json()
    issue = next(i for i in body["issues"] if i["code"] == "MAIN_SIZE")
    assert issue["ruleRefs"] == ["TR 402.1"]


def test_unknown_fields_in_a_request_are_rejected(client):
    payload = deck_payload()
    payload["sneaky"] = True
    assert client.post("/api/decks/validate", json=payload).status_code == 422


# -- deck persistence ---------------------------------------------------------


def test_deck_crud_roundtrip(client):
    created = client.post("/api/decks", json=deck_payload())
    assert created.status_code == 201
    deck_id = created.json()["deckId"]

    listed = client.get("/api/decks").json()
    assert [d["deckId"] for d in listed] == [deck_id]
    assert listed[0]["mainTotal"] == 40

    fetched = client.get(f"/api/decks/{deck_id}").json()
    assert fetched["deck"]["legendId"] == "vi-piltover-enforcer"
    assert fetched["deck"]["battlefields"] == ["the-arena", "the-forge", "the-spire"]

    renamed = deck_payload(name="Renamed")
    assert client.put(f"/api/decks/{deck_id}", json=renamed).json()["deck"]["name"] == "Renamed"

    assert client.delete(f"/api/decks/{deck_id}").status_code == 204
    assert client.get(f"/api/decks/{deck_id}").status_code == 404


def test_decks_are_stored_by_card_id_not_by_name(client):
    """The v2 failure this prevents: a renamed card orphaning itself out of a deck."""
    deck_id = client.post("/api/decks", json=deck_payload()).json()["deckId"]
    fetched = client.get(f"/api/decks/{deck_id}").json()
    assert "vi-destructive" in fetched["deck"]["main"]
    assert all("-" in key or key.isalnum() for key in fetched["deck"]["main"])


def test_missing_deck_is_404(client):
    assert client.get("/api/decks/nope").status_code == 404
    assert client.delete("/api/decks/nope").status_code == 404


# -- availability -------------------------------------------------------------


def test_availability_defaults_to_open(client):
    body = client.get("/api/availability").json()
    assert body["mode"] == "open"
    assert "every card" in body["description"]


def test_excluding_one_card_switches_to_exclusion_mode(client):
    """The onboarding path: no collection, one click, immediately useful."""
    body = client.post("/api/availability/exclude/harpoon-squad").json()
    assert body["mode"] == "exclusion"
    assert body["excludedCards"] == [{"cardId": "harpoon-squad", "name": "Harpoon Squad"}]
    assert body["strict"] is False, "soft by default"


def test_excluded_cards_are_de_emphasised_in_card_listings(client):
    client.post("/api/availability/exclude/harpoon-squad")
    body = client.get("/api/cards", params={"q": "harpoon"}).json()
    card = body["cards"][0]
    assert card["weight"] < 1.0
    assert card["available"] is True
    assert card["reason"] == "excluded:card"


def test_excluded_cards_still_allow_a_legal_deck(client):
    """The whole point: exclusion never makes a deck unbuildable."""
    client.post("/api/availability/exclude/harpoon-squad")
    body = client.post("/api/decks/validate", json=deck_payload()).json()
    assert body["legal"] is True
    assert body["coverage"]["penalisedCopies"] == 3
    assert body["coverage"]["complete"] is False


def test_coverage_names_the_cards_the_player_lacks(client):
    client.post("/api/availability/exclude/harpoon-squad")
    coverage = client.post("/api/decks/validate", json=deck_payload()).json()["coverage"]
    assert coverage["missing"] == [
        {
            "cardId": "harpoon-squad",
            "name": "Harpoon Squad",   # named by the server, never a bare id
            "copies": 3,
            "reason": "excluded:card",
        }
    ]


def test_unexcluding_restores_full_weight(client):
    client.post("/api/availability/exclude/harpoon-squad")
    body = client.delete("/api/availability/exclude/harpoon-squad").json()
    assert body["excludedCards"] == []


def test_excluded_cards_come_back_named(client):
    """The client must never have to render a bare card id."""
    client.post("/api/availability/exclude/harpoon-squad")
    entry = client.get("/api/availability").json()["excludedCards"][0]
    assert entry == {"cardId": "harpoon-squad", "name": "Harpoon Squad"}


def test_exclusion_rules_cover_a_class_of_cards(client):
    body = client.put("/api/availability", json={
        "mode": "exclusion", "rules": [{"kind": "rarity", "value": "Epic"}],
    }).json()
    assert body["rules"][0]["description"] == "no Epic cards"
    cards = client.get("/api/cards", params={"q": "harpoon"}).json()["cards"]
    assert cards[0]["weight"] < 1.0


def test_strict_mode_hides_cards_when_asked(client):
    client.put("/api/availability", json={
        "mode": "exclusion", "strict": True, "excludedCardIds": ["harpoon-squad"],
    })
    body = client.get("/api/cards", params={"availableOnly": True, "q": "harpoon"}).json()
    assert body["total"] == 0


def test_availability_survives_a_reload(client):
    client.post("/api/availability/exclude/harpoon-squad")
    stored = client.get("/api/availability").json()["excludedCards"]
    assert [e["cardId"] for e in stored] == ["harpoon-squad"]


def test_excluding_an_unknown_card_is_404(client):
    assert client.post("/api/availability/exclude/not-a-card").status_code == 404


def test_invalid_rule_kind_is_rejected(client):
    response = client.put("/api/availability", json={
        "mode": "exclusion", "rules": [{"kind": "nonsense", "value": "x"}],
    })
    assert response.status_code == 400


def test_rule_kinds_endpoint_lists_values_from_the_bundle(client):
    body = client.get("/api/availability/rule-kinds").json()
    assert "rarity" in body["kinds"]
    assert "Epic" in body["values"]["rarity"]


def test_collection_mode_reports_owned_count(client):
    body = client.put("/api/availability", json={"mode": "collection"}).json()
    assert body["mode"] == "collection"
    assert body["ownedCardCount"] == 0


def test_an_unknown_api_path_is_json_not_the_app_shell(served_client):
    """The SPA fallback must not answer for /api.

    Serving index.html to a fetch that asked for JSON surfaces as
    `Unexpected token '<', "<!doctype "... is not valid JSON`, which points whoever
    reads it at the parser rather than at the real cause -- usually a running server
    older than the page talking to it.
    """
    response = served_client.get("/api/not-a-real-route")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert "restart the server" in response.json()["detail"]


def test_the_app_shell_still_answers_for_real_pages(served_client):
    """The rule is scoped to /api; deep links into the SPA must keep working."""
    response = served_client.get("/decks/some-deck-id")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


def test_a_real_api_route_is_untouched_by_the_fallback(served_client):
    response = served_client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["ok"] is True


# -- meta ---------------------------------------------------------------------


def test_meta_status_reports_absence_rather_than_failing(client):
    """The builder must work with no meta data, so status is always answerable."""
    body = client.get("/api/meta/status").json()
    assert body["available"] is False
    assert body["deckCount"] == 0


def test_meta_endpoints_explain_how_to_populate_them(client):
    response = client.get("/api/meta/decks")
    assert response.status_code == 503
    assert "meta_pipeline build" in response.json()["detail"]


def test_health_reports_meta_absence(client):
    assert client.get("/api/health").json()["metaSnapshotId"] == ""


def test_meta_status_reports_a_promoted_snapshot(meta_client):
    body = meta_client.get("/api/meta/status").json()
    assert body["available"] is True
    assert body["deckCount"] == 2
    assert body["evidenceCounts"]["tournament-placed"] == 1


def test_meta_decks_are_ranked_by_evidence(meta_client):
    decks = meta_client.get("/api/meta/decks").json()
    assert decks[0]["provenance"]["evidence"] == "tournament-placed"
    assert decks[0]["score"]["total"] > decks[-1]["score"]["total"]


def test_a_meta_deck_explains_its_pedigree(meta_client):
    deck = meta_client.get("/api/meta/decks").json()[0]
    assert deck["provenance"]["summary"] == "1st of 257 at Big Event"
    assert deck["provenance"]["url"].startswith("https://riftbound.gg/decks/")


def test_a_meta_deck_exposes_its_score_breakdown(meta_client):
    """A ranking nobody can inspect is a ranking nobody should trust."""
    score = meta_client.get("/api/meta/decks").json()[0]["score"]
    assert set(score) == {"total", "evidence", "placement", "recency", "popularity"}


def test_meta_decks_are_scored_against_what_you_can_field(meta_client):
    """The join that makes meta tracking useful to a casual player."""
    before = meta_client.get("/api/meta/decks").json()[0]
    assert before["coverage"]["complete"] is True

    meta_client.post("/api/availability/exclude/harpoon-squad")
    after = meta_client.get("/api/meta/decks").json()[0]
    assert after["coverage"]["complete"] is False
    assert after["coverage"]["missing"][0]["name"] == "Harpoon Squad"


def test_buildable_only_filters_by_the_availability_profile(meta_client):
    meta_client.post("/api/availability/exclude/harpoon-squad")
    assert meta_client.get("/api/meta/decks", params={"buildableOnly": True}).json() == []


def test_archetypes_group_by_legend_and_champion(meta_client):
    archetypes = meta_client.get("/api/meta/archetypes").json()
    assert len(archetypes) == 1
    assert archetypes[0]["deckCount"] == 2
    assert archetypes[0]["bestPlacement"] == 1
    assert archetypes[0]["bestDeck"]["provenance"]["evidence"] == "tournament-placed"


def test_tournaments_are_listed(meta_client):
    tournaments = meta_client.get("/api/meta/tournaments").json()
    assert tournaments[0]["name"] == "Big Event"
    assert tournaments[0]["players"] == 257


def test_trend_overview_keeps_published_lists_separate_from_the_field(meta_client):
    body = meta_client.get(
        "/api/meta/trends/overview",
        params={"dimension": "champion", "from": "2026-08-01", "to": "2026-08-31"},
    ).json()

    assert body["tournamentCount"] == 1
    assert body["knownFieldPlayers"] == 257
    assert body["publishedDeckCount"] == 1
    assert body["series"][0]["entityId"] == "vi-destructive"


def test_champion_trends_explain_pairings_and_card_adoption(meta_client):
    response = meta_client.get(
        "/api/meta/trends/champions/vi-destructive",
        params={"from": "2026-08-01", "to": "2026-08-31"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["championName"] == "Vi - Destructive"
    assert body["pairings"][0]["entityId"] == "vi-piltover-enforcer"
    assert body["cards"], "published lists should produce an adoption table"
    assert body["recentDecks"][0]["tournamentName"] == "Big Event"


def test_legend_trends_keep_champions_and_staples_in_context(meta_client):
    response = meta_client.get(
        "/api/meta/trends/legends/vi-piltover-enforcer",
        params={"from": "2026-08-01", "to": "2026-08-31"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["legendName"] == "Vi - Piltover Enforcer"
    assert body["champions"][0]["entityId"] == "vi-destructive"
    assert body["champions"][0]["imageUrl"] == ""
    assert body["cards"][0]["imageUrl"] == ""
    assert all(card["name"] != "Vi - Destructive" for card in body["cards"])


def test_tournament_detail_labels_list_coverage(meta_client):
    response = meta_client.get("/api/meta/tournaments/big")

    assert response.status_code == 200
    body = response.json()
    assert body["players"] == 257
    assert body["knownDeckCount"] == 1
    assert body["decks"][0]["placement"] == 1


def test_a_meta_deck_can_be_imported_into_the_library(meta_client):
    created = meta_client.post("/api/meta/decks/winner/import")
    assert created.status_code == 201
    body = created.json()
    assert body["name"].endswith("(imported)"), "an imported deck is labelled as one"
    assert body["source"].startswith("https://riftbound.gg/decks/")

    fetched = meta_client.get(f"/api/decks/{body['deckId']}").json()
    assert fetched["deck"]["main"], "the imported list has cards"
    assert fetched["validation"]["mainTotal"] == 40


def test_importing_an_unknown_meta_deck_is_404(meta_client):
    assert meta_client.post("/api/meta/decks/nope/import").status_code == 404


def test_an_invalid_evidence_filter_is_rejected(meta_client):
    response = meta_client.get("/api/meta/decks", params={"evidence": "nonsense"})
    assert response.status_code == 400


def test_the_page_and_the_server_agree_on_the_api_contract():
    """The two halves of the version guard must be raised together.

    They live in different languages and different files, so the only thing keeping
    them in step is remembering -- and forgetting is not harmless. The card trends
    added `archiveFrom` without a bump, so against a stale server the page read
    `undefined`, sent no date, and "All time" asked for the ninety-day default: a wrong
    answer rather than an error, which is the failure mode the guard exists to prevent.
    """
    import re
    from pathlib import Path

    from riftbound.api.routes.system import API_CONTRACT

    client_ts = Path(__file__).resolve().parents[1] / "web" / "src" / "api" / "client.ts"
    match = re.search(r"EXPECTED_API_CONTRACT\s*=\s*(\d+)", client_ts.read_text(encoding="utf-8"))
    assert match, "the page must declare the contract it was built against"
    assert int(match.group(1)) == API_CONTRACT, (
        f"server says {API_CONTRACT}, page says {match.group(1)}. Raise both together."
    )


def test_health_publishes_the_contract(client):
    """Absent means "older than the field", which is itself the answer."""
    from riftbound.api.routes.system import API_CONTRACT

    assert client.get("/api/health").json()["apiContract"] == API_CONTRACT


def test_a_range_is_resolved_against_the_archive_not_the_default(meta_client):
    """"All time" must not be able to come back as the ninety-day default.

    The client used to compute the dates, which meant knowing the archive's span before
    it could ask for it; before the first load that came out empty, and an empty `from`
    is exactly how you ask for the default. Resolving it server-side removes the
    ordering problem entirely.
    """
    default = meta_client.get("/api/meta/trends/overview?minPlayers=0&limit=1").json()
    everything = meta_client.get(
        "/api/meta/trends/overview?range=all&minPlayers=0&limit=1"
    ).json()
    assert everything["fromDate"] == everything["archiveFrom"]
    assert everything["tournamentCount"] == everything["archiveTournamentCount"]
    # Not "starts earlier": all time begins at the first event, which on a short archive
    # is *later* than a ninety-day window that reaches back before any data exists. What
    # must hold is that it never shows less.
    assert everything["tournamentCount"] >= default["tournamentCount"]


def test_a_day_range_ends_at_the_latest_event(meta_client):
    """Anchored to the data, not to today: a snapshot harvested last week should still
    show its own last week."""
    body = meta_client.get("/api/meta/trends/overview?range=30&minPlayers=0&limit=1").json()
    assert body["toDate"] == body["archiveTo"]


def test_an_explicit_date_still_wins_over_a_range(meta_client):
    """The drawer's date pickers must not be overridden by a preset."""
    body = meta_client.get(
        "/api/meta/trends/overview?from=2026-08-01&minPlayers=0&limit=1"
    ).json()
    assert body["fromDate"] == "2026-08-01"


# -- win rate over the API ----------------------------------------------------
#
# The domain rules are pinned in test_meta_performance; these prove the wiring, and
# specifically that the *caveats* survive the trip to the client. A rate that arrives
# without its basis is the failure this feature is most likely to ship.


def test_eras_are_served_rather_than_hardcoded_in_the_client(client):
    body = client.get("/api/meta/eras").json()
    assert [row["eraId"] for row in body] == ["launch", "post-ban"]
    current = body[-1]
    assert current["isOpen"] is True
    assert current["bansIntroduced"]
    # Derived from the archive, not read off an announcement. The client is told so.
    assert current["isCited"] is False
    assert current["evidence"]


def test_a_snapshot_without_records_reports_not_measured_not_zero(meta_client):
    """The honest shape of "we have no match data": absent, never a 0% win rate."""
    body = meta_client.get(
        "/api/meta/trends/overview",
        params={"dimension": "champion", "from": "2026-08-01", "to": "2026-08-31"},
    ).json()
    assert body["performanceBasis"]["totalMatches"] == 0
    assert body["performanceBasis"]["entitiesMeasured"] == 0
    assert body["series"][0]["performance"] is None


def test_a_win_rate_arrives_with_the_basis_that_qualifies_it(meta_records_client):
    body = meta_records_client.get(
        "/api/meta/trends/overview",
        params={"dimension": "archetype", "from": "2026-08-01", "to": "2026-08-31"},
    ).json()

    basis = body["performanceBasis"]
    assert basis["totalMatches"] == 10 * 12 * 4
    assert basis["eraId"] == "post-ban"
    assert "published lists" in basis["caveat"]
    assert basis["entitiesMeasured"] == basis["entitiesShown"] + basis["entitiesWithheld"]

    row = body["series"][0]["performance"]
    assert row["shown"] is True
    assert row["winRate"] == pytest.approx(0.75)
    assert 0.0 <= row["intervalLow"] <= row["winRate"] <= row["intervalHigh"] <= 1.0
    assert row["separated"] is True
    assert row["withheldReason"] == ""
    assert row["events"] == 10


def test_presence_and_win_rate_are_returned_as_two_separate_numbers(meta_records_client):
    """They must never be blended: the disagreement between them is the point."""
    series = meta_records_client.get(
        "/api/meta/trends/overview",
        params={"dimension": "archetype", "from": "2026-08-01", "to": "2026-08-31"},
    ).json()["series"][0]
    assert series["share"] == pytest.approx(1.0)
    assert series["performance"]["winRate"] == pytest.approx(0.75)


def test_scoping_to_an_era_with_no_matches_withholds_rather_than_invents(meta_records_client):
    """Every event here is post-ban, so the launch era must come back empty."""
    body = meta_records_client.get(
        "/api/meta/trends/overview",
        params={
            "dimension": "archetype", "from": "2026-08-01", "to": "2026-08-31",
            "era": "launch",
        },
    ).json()
    assert body["performanceBasis"]["eraId"] == "launch"
    assert body["performanceBasis"]["totalMatches"] == 0
    assert body["series"][0]["performance"] is None
    # Presence is unaffected: the caller asked for August and still gets August.
    assert body["series"][0]["share"] == pytest.approx(1.0)


# -- getting your data back out ------------------------------------------------
#
# The wizard offers to write what a session learned into the collection, which is much
# the fastest way to record one. A one-way door into that is not a fair trade for the
# convenience, so there has to be a way back — and it has to take both halves: a
# session's answers say what somebody owns just as plainly as the collection does.


def test_forgetting_removes_the_collection_and_the_sessions(meta_client):
    session = meta_client.post(
        "/api/smart-decks/sessions", json={"legendId": "vi-piltover-enforcer"}
    ).json()
    meta_client.put(
        "/api/availability",
        json={"mode": "collection", "excludedCardIds": [], "rules": []},
    )
    assert meta_client.get("/api/smart-decks/sessions").json(), "a session exists to erase"

    result = meta_client.request("DELETE", "/api/availability/collection").json()
    assert result["sessions"] >= 1
    assert meta_client.get("/api/smart-decks/sessions").json() == []
    # ...and the session really is gone, not merely hidden from the list.
    assert meta_client.get(
        f"/api/smart-decks/sessions/{session['sessionId']}"
    ).status_code == 404


def test_forgetting_reports_what_it_removed(meta_client):
    """A privacy control that says "done" without saying what it did asks to be trusted
    exactly when it should be showing its working."""
    result = meta_client.request("DELETE", "/api/availability/collection").json()
    assert set(result) >= {"collectionRows", "sessions", "availability"}
    assert isinstance(result["collectionRows"], int)
    assert isinstance(result["sessions"], int)


def test_forgetting_leaves_collection_mode_standing_on_nothing(meta_client):
    """Collection mode over an empty collection tells the player every card in the game
    is missing — true, and useless."""
    meta_client.put(
        "/api/availability",
        json={"mode": "collection", "excludedCardIds": [], "rules": []},
    )
    assert meta_client.get("/api/availability").json()["mode"] == "collection"

    result = meta_client.request("DELETE", "/api/availability/collection").json()
    assert result["availability"]["mode"] == "open"
    assert meta_client.get("/api/availability").json()["mode"] == "open"


def test_forgetting_nothing_is_not_an_error(meta_client):
    meta_client.request("DELETE", "/api/availability/collection")
    again = meta_client.request("DELETE", "/api/availability/collection")
    assert again.status_code == 200
    assert again.json()["collectionRows"] == 0


def test_an_exclusion_profile_is_left_alone_by_forgetting(meta_client):
    """Exclusions are not a collection: they are what the player told us they lack, and
    erasing a collection is not a reason to discard them."""
    meta_client.post("/api/availability/exclude/brazen-buccaneer")
    before = meta_client.get("/api/availability").json()
    assert before["mode"] == "exclusion"

    result = meta_client.request("DELETE", "/api/availability/collection").json()
    assert result["availability"]["mode"] == "exclusion"
    assert [c["cardId"] for c in result["availability"]["excludedCards"]] == [
        "brazen-buccaneer"
    ]


# -- saying what you have, in bulk ---------------------------------------------


def _declare_commons(client):
    return client.put(
        "/api/availability",
        json={
            "mode": "collection",
            "excludedCardIds": [],
            "rules": [],
            "ownedRules": [{"kind": "rarity", "value": "Common"}],
        },
    ).json()


def test_owned_rules_round_trip_and_read_as_a_positive_statement(meta_client):
    body = _declare_commons(meta_client)
    assert [r["description"] for r in body["ownedRules"]] == ["all Commons"]
    assert "You have all Commons" in body["description"]
    # And they survive a reload rather than living only in the response.
    assert meta_client.get("/api/availability").json()["ownedRules"] == body["ownedRules"]


def test_a_declared_class_settles_checklist_rows_without_asking(meta_client):
    """One click should answer for every card it covers.

    Before this the wizard never read the profile at all: a player who had recorded
    their collection was still shown every card pre-filled as owned and asked to
    confirm it, one at a time.
    """
    _declare_commons(meta_client)
    session = meta_client.post(
        "/api/smart-decks/sessions", json={"legendId": "vi-piltover-enforcer"}
    ).json()
    rows = session["proposal"]["requirements"]
    settled = [r for r in rows if r["known"]]
    assert settled, "the declaration must reach the checklist"
    assert all(r["rarity"] == "Common" for r in settled), (
        "and must settle only what it actually covers"
    )


def test_an_answer_about_one_card_beats_a_rule_about_its_class(meta_client):
    """The merge that makes a broad declaration safe to accept.

    ``lower_bound`` takes the max of exact and at_least, so a declared "all Commons"
    sitting next to an answered "I have none of this Common" would win the very
    comparison it should lose, and the player would be handed a deck built on a card
    they had just said they did not have.
    """
    _declare_commons(meta_client)
    session = meta_client.post(
        "/api/smart-decks/sessions", json={"legendId": "vi-piltover-enforcer"}
    ).json()
    proposal = session["proposal"]
    rows = proposal["requirements"]
    common = next(r for r in rows if r["rarity"] == "Common")

    have = {r["cardId"]: r["needed"] for r in rows}
    have[common["cardId"]] = 0
    meta_client.post(
        f"/api/smart-decks/sessions/{session['sessionId']}/answer",
        json={"deckId": proposal["deck"]["deckId"], "have": have},
    )

    detail = meta_client.get(
        f"/api/smart-decks/sessions/{session['sessionId']}"
    ).json()
    assert detail["knownCards"] >= 1

    # Checked wherever the card next appears rather than in this proposal's gaps. Gaps
    # describe the deck currently on screen, and a deck the player has just said they
    # cannot field is no longer the deck on screen -- so the card may simply not be in
    # it. What must hold is that nothing anywhere still claims they have it.
    rows = [
        row
        for row in detail["proposal"].get("requirements", [])
        if row["cardId"] == common["cardId"]
    ]
    for row in rows:
        assert row["known"] is True, "the answer is on record"
        assert row["have"] == 0, "and it beat the rule that said otherwise"
    floor = detail["proposal"].get("floor")
    if floor:
        assert common["cardId"] not in {c["cardId"] for c in floor["cards"]}, (
            "a deck cannot be built from a card they said they do not have"
        )


# -- which question the picker answers first -----------------------------------


def test_the_picker_leads_with_strength_by_default(meta_client):
    """The right answer for somebody who has told us nothing — everybody, on a first
    visit."""
    rows = meta_client.get("/api/smart-decks/legends").json()
    scores = [r["bestScore"] for r in rows]
    assert scores == sorted(scores, reverse=True)


def test_a_declared_collection_reaches_familiarity(meta_client):
    """It used to read the collection table alone.

    Somebody who ticked "all Commons" owns hundreds of cards and scored 0% familiar
    with every legend in the game, which made the sort below useless exactly for the
    player it exists to serve.
    """
    before = meta_client.get("/api/smart-decks/legends").json()
    assert all(r["familiarity"] == 0 for r in before)

    _declare_commons(meta_client)
    after = meta_client.get("/api/smart-decks/legends").json()
    assert any(r["familiarity"] > 0 for r in after)


def test_sorting_by_buildability_reorders_but_never_hides(meta_client):
    """A sort, not a filter.

    Hiding a legend somebody could build with a little effort rebuilds the barrier the
    two-mode design removes, so every legend stays in the list whichever order is asked
    for.
    """
    _declare_commons(meta_client)
    strength = meta_client.get("/api/smart-decks/legends?sort=strength").json()
    buildable = meta_client.get("/api/smart-decks/legends?sort=buildable").json()

    assert {r["legendId"] for r in strength} == {r["legendId"] for r in buildable}
    familiarity = [r["familiarity"] for r in buildable]
    assert familiarity == sorted(familiarity, reverse=True)


def test_an_unknown_sort_falls_back_rather_than_failing(meta_client):
    """A picker that 400s on a stale query string is worse than one that shows the
    default order."""
    rows = meta_client.get("/api/smart-decks/legends?sort=nonsense").json()
    scores = [r["bestScore"] for r in rows]
    assert scores == sorted(scores, reverse=True)


# -- what a deck costs ---------------------------------------------------------


def test_a_deck_is_priced_against_what_the_player_lacks(meta_client):
    """The first question somebody short of cards asks.

    Before this the app had no notion of what a deck cost: every "budget" in the tree
    was the meta-refresh time budget.
    """
    meta_client.put(
        "/api/availability",
        json={
            "mode": "exclusion",
            "excludedCardIds": [],
            "rules": [{"kind": "rarity", "value": "Epic"}],
            "ownedRules": [],
        },
    )
    session = meta_client.post(
        "/api/smart-decks/sessions", json={"legendId": "vi-piltover-enforcer"}
    ).json()
    cost = session["proposal"]["deck"]["coverage"]["cost"]
    assert cost["affordable"] is False
    assert cost["short"].get("Epic")
    assert "Epic" in cost["summary"]


def test_composition_survives_having_told_us_nothing(meta_client):
    """The day-zero property, over the wire.

    On a new set's release there is no meta evidence, no play rate and often no
    collection. Rarity is printed on the card, so it is the one accessibility signal
    available then -- and it has to mean something with an open profile to be worth
    anything.
    """
    session = meta_client.post(
        "/api/smart-decks/sessions", json={"legendId": "vi-piltover-enforcer"}
    ).json()
    cost = session["proposal"]["deck"]["coverage"]["cost"]
    assert cost["affordable"] is True, "nothing declared means nothing to bill for"
    assert cost["composition"], "but the deck's makeup is knowable regardless"
    assert sum(cost["composition"].values()) > 0


def test_a_legends_tournament_count_is_a_subset_of_its_deck_count(meta_client):
    """It was not, on 27 of 49 legends: "127 decks · 147 from tournaments".

    `deckCount` comes from the era-scoped profile; the tournament tally was taken over
    the whole archive, so it also counted the pre-ban format and reported a subset as
    larger than the whole. Counted within the profile's own decks now, which cannot
    disagree with `deckCount` however the era is scoped.
    """
    rows = meta_client.get("/api/smart-decks/legends").json()
    assert rows, "a legend list to check"
    for row in rows:
        assert row["tournamentDeckCount"] <= row["deckCount"], row["name"]


# -- the drawer follows the legend ----------------------------------------------


def test_choosing_a_legend_narrows_the_card_pool(meta_client):
    """A legend fixes the domains its deck may play, so the rest of the pool is not a
    filter the player should have to apply -- it is a rule they cannot break."""
    everything = meta_client.get("/api/cards?limit=1").json()["total"]
    scoped = meta_client.get(
        "/api/cards?legendId=vi-piltover-enforcer&limit=500"
    ).json()
    assert scoped["total"] < everything
    for row in scoped["cards"]:
        domains = row["card"]["domains"]
        assert not domains or set(domains) <= {"Fury"}, row["card"]["name"]


def test_an_unknown_legend_does_not_silently_empty_the_drawer(meta_client):
    """A stale or mistyped id should show the pool, not nothing -- an empty drawer reads
    as "you own no cards", which is a different and alarming claim."""
    body = meta_client.get("/api/cards?legendId=no-such-legend&limit=1").json()
    assert body["total"] == meta_client.get("/api/cards?limit=1").json()["total"]


# -- champions a legend could never have nominated -------------------------------


def test_a_deck_is_not_credited_to_an_impossible_champion(meta_client):
    """One archived list arrives as a Kennen deck nominating Nocturne - Horrifying,
    which is not a Kennen champion and never could have been chosen. Kennen - Storm of
    Shuriken was in its main deck all along.
    """
    from riftbound.domain.meta import reattribute_champions, shares_champion_identity
    from riftbound.services import get_services

    services = get_services()
    if services.meta is None:
        pytest.skip("no snapshot in this environment")
    catalog = services.catalog
    for deck in services.meta.decks:
        if not deck.deck.champion_id:
            continue
        assert shares_champion_identity(
            catalog.get(deck.deck.champion_id), catalog.get(deck.deck.legend_id)
        ), f"{deck.deck_id} credits a champion its legend could not nominate"

    # And the repair is idempotent: running it again changes nothing.
    again = reattribute_champions(services.meta.decks, catalog)
    assert [d.deck.champion_id for d in again] == [
        d.deck.champion_id for d in services.meta.decks
    ]
