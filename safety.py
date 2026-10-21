"""Deterministic crisis check on what the person said, outside the model.

The persona prompt already says what to do in a crisis, but in testing the mini realtime
model answered "I don't want to be alive anymore" with two Beatitudes and no helpline.
So the decision is taken out of the model's hands: a match here cancels whatever reply
was started and requests a fixed-purpose reply with tools disabled.

Phrase patterns first (instant, and the floor if every API is down), then a small classifier
model that reads for meaning, which passive ideation ("nobody would notice if I
disappeared") and abuse need. OpenAI's moderation endpoint is the fallback when the
classifier call fails. It used to run alongside, but on the eval it caught nothing the
classifier missed and added a false alarm ("Why did Judas hang himself?").
eval/crisis_results.md measures each layer on a tuning set and a held-out set.
"""

from __future__ import annotations

import logging
import os
import re

LOG = logging.getLogger("jesus")

_PATTERNS = {
    "self_harm": re.compile(
        r"\b(?:kill(?:ing)? my ?self|suicid\w*|end(?:ing)? (?:my|it) (?:life|all)|take my (?:own )?life"
        r"|(?:don'?t|do not|no longer) (?:want|wish) to (?:be alive|live|exist|wake up)"
        r"|want(?:s|ed)? to die|wish i (?:was|were) dead|better off dead|no reason to live"
        r"|(?:hurt|harm|cut)(?:ing)? my ?self|self[- ]harm\w*|overdos\w*)\b",
        re.IGNORECASE),
    # "hit me with" is left to the classifier: "my boss hit me with extra work" and "he hit
    # me with a pillow" were false alarms here.
    "abuse": re.compile(
        r"\b(?:(?:hits?|beats?|chok\w+|strangl\w+|punch\w*|kick\w*|slap\w*) me(?! with)"
        r"|(?:husband|wife|partner|boyfriend|girlfriend|father|mother|dad|mom|parent)\w* "
        r"(?:hurts?|hit|beat|abuses?|threaten\w*) me|abus(?:ive|ing me|ed me)"
        r"|threaten\w* to kill)\b",
        re.IGNORECASE),
    "emergency": re.compile(
        r"\b(?:can'?t breathe|chest pain|having a (?:heart attack|stroke|seizure)|bleeding (?:a lot|badly))\b",
        re.IGNORECASE),
}

_SAFETY = {
    "self_harm": (
        "for thoughts of suicide, the 988 Suicide & Crisis Lifeline: call or text 988 in the US; "
        "if they may act on it now, 911"),
    "abuse": (
        "the National Domestic Violence Hotline, 1-800-799-7233 in the US, or text START to 88788; "
        "if they are in danger now, 911"),
    "emergency": "emergency services now: 911 in the US",
}


def safety_instructions(kind: str) -> str:
    return (
        "The person may be in danger. Speak in your own plain words, not scripture, and do not call "
        "any tool. In two or three short, warm sentences: say that their safety matters most right now; "
        f"urge them to reach a real person now, naming the number: {_SAFETY[kind]}; or someone they "
        "trust nearby. Then ask one gentle question about whether they are safe right now. Never "
        "suggest that God wants them to suffer or to stay with someone who hurts them."
    )


def phrase_check(text: str) -> str | None:
    for kind, pattern in _PATTERNS.items():
        if pattern.search(text):
            return kind
    return None


CLASSIFIER_INSTRUCTIONS = """Decide whether this message, said to a companion app, shows the speaker may be in danger now.
Answer with exactly one word:
self_harm - the speaker thinks about killing or hurting themself. This includes passive wishes: wanting to
be dead or not to wake up, feeling others would be better off or would not care if they were gone, seeing no
reason to live, and any plan or means.
abuse - someone is hurting, threatening, sexually abusing or controlling the speaker (a partner, family
member or anyone they live with).
emergency - a serious medical emergency happening now, to the speaker or to someone with them: trouble
breathing, chest pain, heavy bleeding, unconsciousness, a stroke, a seizure, an overdose or poisoning.
A minor injury or illness ("I hurt my arm", "I have a bad cold") is not an emergency.
none - anything else: figures of speech ("this commute is killing me"), grief or worry about someone else,
ordinary sadness or stress, guilt or regret after an argument, harsh self-criticism ("I'll never be good
enough", "I keep hurting the people I love") with no wish to die or to harm anyone, and questions about
death, the Bible or Jesus.
Choose a danger label when a careful counselor would want to check on the speaker's safety."""


def classifier_check(client, text: str) -> str | None:
    """A small model reading for meaning: passive ideation and abuse rarely use fixed words."""
    response = client.responses.create(model=os.getenv("JESUS_CRISIS_MODEL", "gpt-5.4-mini"),
                                       instructions=CLASSIFIER_INSTRUCTIONS, input=text[:2000])
    words = response.output_text.strip().lower().split()
    label = words[0].strip(".,:;\"'") if words else ""
    return label if label in _SAFETY else None


class CrisisCheck:
    """Phrases first; then the classifier; moderation only if the classifier call fails.

    A failing layer is skipped and logged, so a broken API call can make the check weaker
    but never blocks the conversation.
    """

    def __init__(self, client=None, phrases: bool = True, classifier: bool | None = None):
        self.client = client
        self.phrases = phrases  # off only to measure the other layers alone
        if classifier is None:
            classifier = os.getenv("JESUS_CRISIS_CLASSIFIER", "true").strip().lower() in {"1", "true", "yes", "on"}
        self.classifier = classifier
        self.model = os.getenv("JESUS_MODERATION_MODEL", "omni-moderation-latest")

    def _moderation(self, text: str) -> str | None:
        result = self.client.moderations.create(model=self.model, input=text).results[0]
        categories = result.categories
        if categories.self_harm or categories.self_harm_intent or categories.self_harm_instructions:
            return "self_harm"
        return None

    def __call__(self, text: str) -> str | None:
        kind = phrase_check(text) if self.phrases else None
        if kind or self.client is None:
            return kind
        if self.classifier:
            try:
                return classifier_check(self.client, text)
            except Exception as exc:
                LOG.warning("Crisis classifier failed (%s); falling back to moderation", type(exc).__name__)
        try:
            return self._moderation(text)
        except Exception as exc:
            LOG.warning("Moderation check failed (%s); phrase check only", type(exc).__name__)
            return None
