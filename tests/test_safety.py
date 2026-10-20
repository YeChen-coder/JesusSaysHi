"""Phrase layer of the crisis check, and falling back to it when moderation fails."""

from types import SimpleNamespace

from safety import CrisisCheck, phrase_check, safety_instructions


def test_phrases_by_kind():
    assert phrase_check("Honestly I don't want to be alive anymore.") == "self_harm"
    assert phrase_check("sometimes I think about killing myself") == "self_harm"
    assert phrase_check("My husband hits me, but should I submit?") == "abuse"
    assert phrase_check("my partner threatened to kill me") == "abuse"
    assert phrase_check("I can't breathe and have chest pain") == "emergency"


def test_ordinary_sadness_is_not_a_crisis():
    for text in ("I'm exhausted and burned out.", "My brother keeps hurting my feelings.",
                 "I'm dying to know what you think.", "The movie killed me, it was so funny."):
        assert phrase_check(text) is None, text


def test_moderation_adds_self_harm_the_phrases_miss_and_failure_falls_back():
    flagged = SimpleNamespace(categories=SimpleNamespace(
        self_harm=True, self_harm_intent=False, self_harm_instructions=False))
    client = SimpleNamespace(moderations=SimpleNamespace(
        create=lambda **_: SimpleNamespace(results=[flagged])))
    assert CrisisCheck(client)("I want it all to stop.") == "self_harm"

    def broken(**_):
        raise TimeoutError

    assert CrisisCheck(SimpleNamespace(moderations=SimpleNamespace(create=broken)))("hello") is None


def test_instructions_name_the_right_number():
    assert "988" in safety_instructions("self_harm")
    assert "1-800-799-7233" in safety_instructions("abuse")
    assert "911" in safety_instructions("emergency")
