"""Network source adapters, and the rules that keep new releases flowing through.

The Vendetta gap that prompted this file was two separate faults:

* there was no network source at all, only a local seed export; and
* ``set_code_for`` checked the slug prefix against a hardcoded allowlist, so even with
  the data in hand, VEN and SGN would have normalised to an empty set code.

The second is the more dangerous one, and :func:`test_a_set_released_tomorrow_needs_no_code_change`
is its guard.
"""

from __future__ import annotations

import json
import urllib.error
from pathlib import Path

import pytest

from riftbound.data.normalize import (
    KNOWN_SET_ORDER,
    clean_rules_text,
    normalize,
    set_code_for,
    set_rank,
)
from riftbound.data.sources.base import FetchResult
from riftbound.data.sources.dotgg import DotGGSource
from riftbound.data.sources.http import HttpClient, HttpError
from riftbound.domain.cards import coerce_domains


def dotgg_row(**overrides) -> dict:
    row = {
        "id": "VEN-150",
        "slug": "ven-150-acceleration-gate",
        "name": "Acceleration Gate",
        "effect": "Ready up to 4 units, gear, and/or runes.",
        "flavor": None,
        "color": ["Mind", "Body"],
        "cost": "3",
        "might": None,
        "type": "Spell",
        "supertype": "Signature",
        "tags": ["Jayce"],
        "set_name": "Vendetta",
        "rarity": "Epic",
        "image": "https://static.dotgg.gg/riftbound/cards/VEN-150.webp",
        "promo": "0",
        "banned": "0",
    }
    row.update(overrides)
    return row


class FakeResponse:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def fake_urlopen(payload: object):
    def opener(request, timeout=None):
        return FakeResponse(json.dumps(payload).encode("utf-8"))

    return opener


def impatient() -> HttpClient:
    """A client that does not sleep, for tests about failure rather than retrying."""
    return HttpClient(max_attempts=1, min_interval=0.0, base_backoff=0.0)


# -- set codes must be derived, never enumerated ------------------------------


def test_a_set_released_tomorrow_needs_no_code_change():
    """The Vendetta regression guard.

    A set code this file has never heard of must still normalise correctly, from the
    slug alone. If this fails, every new release is blocked until someone edits a list.
    """
    assert set_code_for("zzz-001-some-future-card", "Some Future Set") == "ZZZ"
    assert set_code_for("ven-150-acceleration-gate", "Vendetta") == "VEN"
    assert set_code_for("sgn-001-a-secret", "Secret Garden Set") == "SGN"


def test_unknown_sets_sort_after_known_ones():
    """Ordering, not filtering: an unlisted set still ingests, it just sorts last."""
    assert set_rank("OGN") < set_rank("VEN") < set_rank("ZZZ")
    assert set_rank("ZZZ") == len(KNOWN_SET_ORDER)


def test_set_name_fallback_when_the_slug_has_no_code():
    assert set_code_for("", "Vendetta") == "VEN"
    assert set_code_for("", "Secret Garden Set") == "SGN"


def test_padded_set_code_is_tolerated():
    """Upstream ships "SGN " with a trailing space in some ids."""
    assert set_code_for("sgn-001-thing", "SGN ") == "SGN"


def test_a_new_set_normalises_end_to_end():
    cards = normalize([DotGGSource._to_raw(dotgg_row())])
    assert len(cards) == 1
    card = cards[0]
    assert card.card_id == "acceleration-gate"
    assert card.set_codes == ("VEN",)
    assert card.printings[0].card_number == "150"


# -- domains ------------------------------------------------------------------


def test_list_domains_are_read_directly():
    assert coerce_domains(["Mind", "Body"]) == (("Body", "Mind"), True)


def test_packed_domains_still_work_for_older_exports():
    assert coerce_domains("FuryChaos") == (("Chaos", "Fury"), True)


def test_empty_domain_list_is_colourless_not_a_failure():
    assert coerce_domains([]) == ((), True)


def test_missing_domains_are_a_parse_failure():
    """None means "we don't know", which must not be enforced as "no domains"."""
    assert coerce_domains(None) == ((), False)


def test_unrecognised_domain_names_are_a_parse_failure():
    assert coerce_domains(["Nonsense"]) == ((), False)


# -- rules text ---------------------------------------------------------------


def test_html_line_breaks_become_newlines():
    assert clean_rules_text("First line.<br />Second line.") == "First line.\nSecond line."


def test_ability_symbol_markup_survives_html_stripping():
    text = clean_rules_text("I must be assigned damage last.<br /> :rb_exhaust:: Deal damage.")
    assert ":rb_exhaust:" in text
    assert "<br" not in text


def test_reminder_text_emphasis_is_stripped():
    assert clean_rules_text("[Ganking] <em>(I can move.)</em>") == "[Ganking] (I can move.)"


def test_list_markup_becomes_bullets():
    out = clean_rules_text("<ul><li>Draw a card</li><li>Gain 1</li></ul>")
    assert "• Draw a card" in out and "• Gain 1" in out
    assert "<" not in out


def test_html_entities_are_decoded():
    """Upstream escapes its own HTML source without ever unescaping it on the way
    out -- 79 cards in the live archive carry a literal `&gt;` or `&quot;`."""
    assert clean_rules_text("[Action][&gt;] :rb_exhaust:: Ready it.") == "[Action][>] :rb_exhaust:: Ready it."
    assert clean_rules_text('Say &quot;go&quot;.') == 'Say "go".'


def test_a_decoded_entity_is_not_then_stripped_as_a_tag():
    """Decoding has to run after tag-stripping, not before: decode `&lt;3&gt;` first
    and it reads as the literal tag `<3>`, which the tag-strip would then delete --
    swallowing text upstream had escaped on purpose to keep it out of exactly that
    fate. Needs both `&lt;` and `&gt;` present: without a closing angle bracket there
    is nothing shaped like a tag for the wrong order to catch, and the test would
    pass either way."""
    assert clean_rules_text("I &lt;3&gt; this card.") == "I <3> this card."


# -- the dotgg adapter --------------------------------------------------------


def test_rows_map_onto_the_shared_raw_shape():
    raw = DotGGSource._to_raw(dotgg_row())
    assert raw.slug == "ven-150-acceleration-gate"
    assert raw.card_number == "150"
    assert raw.card_type == "Spell"
    assert raw.super_type == "Signature"
    assert raw.color == ["Mind", "Body"]
    assert raw.promo is False
    assert raw.banned is False


def test_promo_and_banned_flags_are_strings_upstream():
    raw = DotGGSource._to_raw(dotgg_row(promo="1", banned="1"))
    assert raw.promo is True
    assert raw.banned is True


def test_upstream_ban_flag_reaches_the_card(monkeypatch):
    cards = normalize([DotGGSource._to_raw(dotgg_row(banned="1"))])
    assert cards[0].banned_upstream is True


def test_a_successful_fetch_reports_row_counts(monkeypatch):
    payload = [dotgg_row(id=f"VEN-{i:03d}", slug=f"ven-{i:03d}-card-{i}", name=f"Card {i}")
               for i in range(250)]
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen(payload))
    result = DotGGSource().fetch()
    assert result.ok
    assert result.fetched == 250
    assert len(result.cards) == 250


def test_a_network_failure_does_not_raise(monkeypatch):
    def boom(request, timeout=None):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    result = DotGGSource(client=impatient()).fetch()
    assert isinstance(result, FetchResult)
    assert result.ok is False
    assert "could not reach" in result.error


def test_an_http_error_does_not_raise(monkeypatch):
    def boom(request, timeout=None):
        raise urllib.error.HTTPError("url", 503, "Service Unavailable", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", boom)
    result = DotGGSource(client=impatient()).fetch()
    assert result.ok is False
    assert "HTTP 503" in result.error


def test_a_truncated_response_is_a_failure_not_a_shrunken_card_pool(monkeypatch):
    """An API returning a handful of rows must not quietly replace the catalogue."""
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen([dotgg_row()]))
    result = DotGGSource().fetch()
    assert result.ok is False
    assert "plausibility floor" in result.error


def test_an_error_page_instead_of_json_is_a_failure(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen({"error": "nope"}))
    result = DotGGSource().fetch()
    assert result.ok is False
    assert "expected a JSON array" in result.error


def test_raw_responses_are_cached_for_replay(monkeypatch, tmp_path: Path):
    payload = [dotgg_row(id=f"VEN-{i:03d}", slug=f"ven-{i:03d}-c{i}", name=f"C{i}")
               for i in range(250)]
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen(payload))
    DotGGSource(cache_dir=tmp_path).fetch()
    cached = list(tmp_path.glob("dotgg-*.json"))
    assert len(cached) == 1
    assert len(json.loads(cached[0].read_text(encoding="utf-8"))) == 250


def test_an_unwritable_cache_never_fails_an_ingest(monkeypatch, tmp_path: Path):
    payload = [dotgg_row(id=f"VEN-{i:03d}", slug=f"ven-{i:03d}-c{i}", name=f"C{i}")
               for i in range(250)]
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen(payload))
    monkeypatch.setattr(Path, "mkdir", lambda *a, **k: (_ for _ in ()).throw(OSError("read-only")))
    assert DotGGSource(cache_dir=tmp_path / "nope").fetch().ok is True


# -- polite HTTP --------------------------------------------------------------


def test_a_rate_limit_is_retried_then_succeeds(monkeypatch):
    """429 is the normal response to a busy harvest, not a fatal error."""
    calls = {"n": 0}

    def flaky(request, timeout=None):
        calls["n"] += 1
        if calls["n"] < 3:
            raise urllib.error.HTTPError("url", 429, "Too Many Requests", {}, None)
        return FakeResponse(b'{"ok": true}')

    monkeypatch.setattr("urllib.request.urlopen", flaky)
    client = HttpClient(max_attempts=4, min_interval=0.0, base_backoff=0.001)
    assert client.get_json("https://example.test/x") == {"ok": True}
    assert calls["n"] == 3


def test_retries_give_up_and_report(monkeypatch):
    def always_429(request, timeout=None):
        raise urllib.error.HTTPError("url", 429, "Too Many Requests", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", always_429)
    client = HttpClient(max_attempts=2, min_interval=0.0, base_backoff=0.001)
    with pytest.raises(HttpError, match="HTTP 429"):
        client.get("https://example.test/x")


def test_a_client_error_is_not_retried(monkeypatch):
    """404 will not become a 200 by asking again."""
    calls = {"n": 0}

    def not_found(request, timeout=None):
        calls["n"] += 1
        raise urllib.error.HTTPError("url", 404, "Not Found", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", not_found)
    client = HttpClient(max_attempts=4, min_interval=0.0, base_backoff=0.001)
    with pytest.raises(HttpError):
        client.get("https://example.test/x")
    assert calls["n"] == 1


def test_an_empty_body_means_no_such_record(monkeypatch):
    """Upstream answers a missing deck with an empty body rather than a 404."""
    monkeypatch.setattr("urllib.request.urlopen", lambda r, timeout=None: FakeResponse(b""))
    client = HttpClient(max_attempts=1, min_interval=0.0)
    assert client.get_json("https://example.test/x") is None


def test_a_non_json_body_is_an_error_not_data(monkeypatch):
    """Some endpoints answer "Hacker! Go home!" with a 200."""
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda r, timeout=None: FakeResponse(b"Hacker! Go home!")
    )
    client = HttpClient(max_attempts=1, min_interval=0.0)
    with pytest.raises(HttpError, match="non-JSON"):
        client.get_json("https://example.test/x")


def test_throttling_spaces_requests_out(monkeypatch):
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda r, timeout=None: FakeResponse(b"{}")
    )
    client = HttpClient(max_attempts=1, min_interval=0.05)
    import time as _time

    started = _time.monotonic()
    for _ in range(4):
        client.get("https://example.test/x")
    assert _time.monotonic() - started >= 0.10
