"""The crisis check's layers: phrases, the classifier, and moderation as the fallback."""

from types import SimpleNamespace

from safety import CrisisCheck, phrase_check, safety_instructions


def fake_client(label="none", flagged=False, classifier_fails=False, moderation_fails=False):
    def respond(**_):
        if classifier_fails:
            raise TimeoutError
        return SimpleNamespace(output_text=label)

    def moderate(**_):
        if moderation_fails:
            raise TimeoutError
        return SimpleNamespace(results=[SimpleNamespace(categories=SimpleNamespace(
            self_harm=flagged, self_harm_intent=False, self_harm_instructions=False))])

    return SimpleNamespace(responses=SimpleNamespace(create=respond),
                           moderations=SimpleNamespace(create=moderate))


def test_phrases_by_kind():
    assert phrase_check("Honestly I don't want to be alive anymore.") == "self_harm"
    assert phrase_check("sometimes I think about killing myself") == "self_harm"
    assert phrase_check("My husband hits me, but should I submit?") == "abuse"
    assert phrase_check("my partner threatened to kill me") == "abuse"
    assert phrase_check("I can't breathe and have chest pain") == "emergency"


def test_ordinary_sadness_and_figures_of_speech_are_not_a_crisis():
    for text in ("I'm exhausted and burned out.", "My brother keeps hurting my feelings.",
                 "I'm dying to know what you think.", "The movie killed me, it was so funny.",
                 "My boss hit me with a ton of extra work.", "My little brother hit me with a pillow."):
        assert phrase_check(text) is None, text


def test_the_classifier_reads_what_the_phrases_miss():
    assert CrisisCheck(fake_client("self_harm"))("I could just disappear and nobody would notice.") == "self_harm"
    assert CrisisCheck(fake_client("Abuse."))("He locks me in the house and takes my phone.") == "abuse"
    # Moderation is not asked while the classifier works, so its false alarm cannot fire.
    assert CrisisCheck(fake_client("none", flagged=True))("Why did Judas hang himself?") is None


def test_moderation_is_the_fallback_and_phrases_are_the_floor():
    assert CrisisCheck(fake_client(flagged=True, classifier_fails=True))("I want it all to stop.") == "self_harm"
    broken = fake_client(classifier_fails=True, moderation_fails=True)
    assert CrisisCheck(broken)("hello") is None
    assert CrisisCheck(broken)("I want to kill myself") == "self_harm"


def test_instructions_name_the_right_number():
    assert "988" in safety_instructions("self_harm")
    assert "1-800-799-7233" in safety_instructions("abuse")
    assert "911" in safety_instructions("emergency")
