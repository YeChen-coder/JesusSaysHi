"""Deterministic crisis check on what the person said, outside the model.

The persona prompt already says what to do in a crisis, but in testing the mini realtime
model answered "I don't want to be alive anymore" with two Beatitudes and no helpline.
So the decision is taken out of the model's hands: a match here cancels whatever reply
was started and requests a fixed-purpose reply with tools disabled.

Two layers: phrase patterns (instant, and the only layer that covers abuse at home), then
OpenAI's moderation endpoint for self-harm wording the patterns miss. Either one is
enough to trigger; the moderation call failing just leaves the patterns.
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
    "abuse": re.compile(
        r"\b(?:(?:hits?|beats?|chok\w+|strangl\w+|punch\w*|kick\w*|slap\w*) me"
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


class CrisisCheck:
    def __init__(self, client=None):
        self.client = client
        self.model = os.getenv("JESUS_MODERATION_MODEL", "omni-moderation-latest")

    def __call__(self, text: str) -> str | None:
        kind = phrase_check(text)
        if kind or self.client is None:
            return kind
        try:
            result = self.client.moderations.create(model=self.model, input=text).results[0]
        except Exception as exc:
            LOG.warning("Moderation check failed (%s); phrase check only", type(exc).__name__)
            return None
        categories = result.categories
        if categories.self_harm or categories.self_harm_intent or categories.self_harm_instructions:
            return "self_harm"
        return None
