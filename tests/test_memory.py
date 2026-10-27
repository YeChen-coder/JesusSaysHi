"""Episodic memory: which episodes are offered, how the note reads, and the check after a reply."""

import asyncio
from types import SimpleNamespace

import memory
from memory import EpisodeRecall, memory_note, overlaps, parallel, told

LUKE_DENIAL = "Luke 22.54 Peter Denies Jesus.txt"
MARK_DENIAL = "Mark 14.66 Peter Denies Jesus.txt"
LAZARUS = "John 11.17 Jesus Comforts Martha and Mary.txt"
BIRTH = "Luke 02.01 The Birth of Jesus.txt"
JUDAS = "Matthew 27.03 Judas Hangs Himself.txt"

EPISODES = {
    LUKE_DENIAL: {"ref": "Luke 22:54-62", "title": "Peter Denies Jesus", "present": True,
                  "parallels": ["Matthew 26:69-75", "Mark 14:66-72", "John 18:15-18"],
                  "text": "Peter sat down among them by the fire in the courtyard. But Peter denied it. "
                          "The rooster crowed. And the Lord turned and looked at Peter, and he wept bitterly."},
    MARK_DENIAL: {"ref": "Mark 14:66-72", "title": "Peter Denies Jesus", "present": True,
                  "parallels": ["Matthew 26:69-75", "Luke 22:54-62", "John 18:15-18"], "text": "Peter denied it."},
    LAZARUS: {"ref": "John 11:17-37", "title": "Jesus Comforts Martha and Mary", "present": True, "parallels": [],
              "text": "Martha said, Lord, if You had been here, my brother would not have died. Jesus wept."},
    BIRTH: {"ref": "Luke 2:1-7", "title": "The Birth of Jesus", "present": False, "parallels": [],
            "text": "She gave birth to her firstborn and laid Him in a manger."},
    JUDAS: {"ref": "Matthew 27:3-10", "title": "Judas Hangs Himself", "present": False, "parallels": [],
            "text": "Judas went away and hanged himself."},
}


class FakeIndex:
    min_score = 0.30

    def __init__(self, ranked):
        self.ranked = ranked  # [(filename, score)], best first
        self.calls = []

    def retrieve(self, query, k, **overrides):
        self.calls.append((query, k, overrides))
        floor = overrides.get("min_score", self.min_score)
        if floor is not None and (not self.ranked or self.ranked[0][1] < floor):
            return []
        return [{"document_keyword": doc, "similarity": score} for doc, score in self.ranked[:k]]


def rewriter(text="grief, a friend's death, Lazarus", fail=False):
    def create(**_):
        if fail:
            raise TimeoutError
        return SimpleNamespace(output_text=text)
    return SimpleNamespace(responses=SimpleNamespace(create=create))


def recall(ranked, told_before=(), **kwargs):
    index = FakeIndex(ranked)
    r = EpisodeRecall(index, rewriter(), episodes=EPISODES, **kwargs)
    memo, offered = r.recall([{"user": "Hi."}, {"user": "My best friend died and I can't stop crying."}],
                             set(told_before))
    return memo, offered, index


def test_the_first_turn_only_listens():
    r = EpisodeRecall(FakeIndex([(LAZARUS, 0.5)]), rewriter(), episodes=EPISODES)
    memo, offered = r.recall([{"user": "Hi, I need to talk."}], set())
    assert offered == [] and memo["why_none"].startswith("first turn")


def test_offers_whole_episodes_with_how_he_knows_them():
    memo, offered, index = recall([(LAZARUS, 0.47), (BIRTH, 0.40)])
    assert [e["doc"] for e in offered] == [LAZARUS, BIRTH]
    assert offered[0]["present"] and not offered[1]["present"]
    assert "Jesus wept" in offered[0]["text"]
    assert memo["query"] == "grief, a friend's death, Lazarus"  # the rewrite, not the raw words
    assert index.calls[0][2] == {}  # RAGFlow's own threshold


def test_one_account_per_event_and_nothing_already_told():
    _, offered, _ = recall([(LUKE_DENIAL, 0.49), (MARK_DENIAL, 0.48), (LAZARUS, 0.40)])
    assert [e["doc"] for e in offered] == [LUKE_DENIAL, LAZARUS]
    _, offered, _ = recall([(MARK_DENIAL, 0.48), (LAZARUS, 0.40)], told_before=[LUKE_DENIAL])
    assert [e["doc"] for e in offered] == [LAZARUS]  # Mark's telling of a story already told


def test_judas_suicide_is_never_recalled():
    _, offered, _ = recall([(JUDAS, 0.42), (LUKE_DENIAL, 0.39)])
    assert [e["doc"] for e in offered] == [LUKE_DENIAL]


def test_abstains_below_the_threshold_and_the_floor_can_be_changed():
    memo, offered, _ = recall([(LAZARUS, 0.25)])
    assert offered == [] and "abstained" in memo["why_none"]
    _, offered, index = recall([(LAZARUS, 0.25)], min_score=None)  # recall on every turn
    assert [e["doc"] for e in offered] == [LAZARUS] and index.calls[0][2] == {"min_score": None}


def test_a_failed_rewrite_searches_with_the_words_as_said():
    index = FakeIndex([(LAZARUS, 0.5)])
    r = EpisodeRecall(index, rewriter(fail=True), episodes=EPISODES)
    memo, offered = r.recall([{"user": "Hi."}, {"user": "My best friend died and I can't stop crying."}], set())
    assert memo["rewrite_failed"] == "TimeoutError" and index.calls[0][0].startswith("My best friend died")
    assert offered


def test_the_note_marks_absent_episodes_and_asks_for_names():
    note = memory_note([dict(EPISODES[LAZARUS]), dict(EPISODES[BIRTH])])
    assert note.startswith("MEMORY:") and "[Jesus Comforts Martha and Mary] You were there." in note
    assert "[The Birth of Jesus] You were not there" in note and "Lazarus" in note
    assert "chapter" in note  # told not to cite chapter and verse


def test_telling_is_seen_by_distinctive_shared_words():
    text = EPISODES[LUKE_DENIAL]["text"]
    assert len(told("I remember Peter by the fire in the courtyard, and the rooster.", text)) >= 3
    assert len(told("My child, I am here with you, and the Lord loves you.", text)) < 3


def test_reference_helpers():
    assert overlaps("Luke 22:61", "Luke 22:54-62") and not overlaps("Luke 22:63", "Luke 22:54-62")
    assert not overlaps("Mark 14:66", "Luke 22:54-62")
    assert parallel(EPISODES[LUKE_DENIAL], EPISODES[MARK_DENIAL])
    assert not parallel(EPISODES[LUKE_DENIAL], EPISODES[LAZARUS])


def test_the_reply_check_marks_a_told_episode_and_spots_other_scripture(tmp_path):
    from test_voice import conversation

    c = conversation(tmp_path)
    episode = {"doc": LUKE_DENIAL, **EPISODES[LUKE_DENIAL]}
    turn = {"episodes": [episode]}
    reply = "I remember Peter by the fire in the courtyard when the rooster crowed. Come to Me, all you who are weary and burdened."
    asyncio.run(c._check_memory_use(reply, turn))
    check = turn["checks"][0]
    assert check["told"][0]["ref"] == "Luke 22:54-62" and LUKE_DENIAL in c.used_refs
    # FakeIndex in test_voice holds Matthew 11:28, which was not offered: recited from elsewhere.
    assert [s["ref"] for s in check["other_scripture"]] == ["Matthew 11:28"]


def test_a_memory_told_with_nothing_offered_is_flagged(tmp_path):
    from test_voice import conversation

    c = conversation(tmp_path)
    turn = {"episodes": []}
    asyncio.run(c._check_memory_use("I remember sitting with Peter at dusk, laughing. You are not alone.", turn))
    assert turn["checks"][0]["memory_without_source"].startswith("I remember sitting with Peter")
    turn = {"episodes": []}
    asyncio.run(c._check_memory_use("That sounds lonely, my friend. You are not alone here.", turn))
    assert "memory_without_source" not in turn["checks"][0]


def test_a_turn_without_memory_is_told_so(tmp_path):
    from test_voice import conversation

    c = conversation(tmp_path)
    without = c._phase_instructions("B", "I feel alone.", "I hear you.", memory_given=False)
    with_memory = c._phase_instructions("B", "I feel alone.", "I hear you.", memory_given=True)
    assert "No particular moment of your life comes to mind" in without
    assert "No particular moment" not in with_memory
    assert "No particular moment" in c._phase_instructions("single", "Hi.")  # the first turn never has one


def test_the_turn_is_read_into_a_kind_and_only_talk_is_remembered():
    def client(output):
        return SimpleNamespace(responses=SimpleNamespace(create=lambda **_: SimpleNamespace(output_text=output)))

    assert memory.read_turn(client('{"kind": "information", "query": ""}'), "Weather in Toronto?") == \
        ("information", "Weather in Toronto?")
    assert memory.read_turn(client('{"kind": "talk", "query": "grief, Lazarus"}'), "x") == ("talk", "grief, Lazarus")
    assert memory.read_turn(client("grief, Lazarus"), "x") == ("talk", "grief, Lazarus")  # not JSON: a plain query
    for kind in ("information", "expert"):
        index = FakeIndex([(LAZARUS, 0.9)])
        r = EpisodeRecall(index, client(f'{{"kind": "{kind}", "query": ""}}'), episodes=EPISODES)
        memo, offered = r.recall([{"user": "Hi."}, {"user": "Is a knee replacement risky?"}], set())
        assert offered == [] and memo["kind"] == kind and index.calls == []  # not even searched


def test_research_is_gated_by_the_turn_kind(tmp_path):
    from test_voice import conversation

    async def scenario(kind):
        c = conversation(tmp_path)
        c.phase_state = {"kind": kind, "kind_ready": asyncio.Event(), "done": False}
        c.phase_state["kind_ready"].set()
        return await c._research_gate("how to fix ModuleNotFoundError")

    assert "professional" in asyncio.run(scenario("expert"))
    assert "not a question for information" in asyncio.run(scenario("talk"))
    assert asyncio.run(scenario("information")) is None


def test_phase_b_carries_the_kind(tmp_path):
    from test_voice import conversation

    c = conversation(tmp_path)
    assert "call research_web now" in c._phase_instructions("B", "Weather?", "Let me see.", kind="information")
    assert "Do not answer it" in c._phase_instructions("B", "Is it risky?", "I hear you.", kind="expert")
    talk = c._phase_instructions("B", "I feel alone.", "I hear you.", memory_given=True, kind="talk")
    assert "They asked for information" not in talk and "This needs a professional" not in talk


def test_a_close_fit_is_asked_for_and_a_loose_one_only_allowed():
    close = memory_note([dict(EPISODES[LAZARUS], score=0.5)])
    loose = memory_note([dict(EPISODES[LAZARUS], score=0.33)])
    assert "tell it now" in close and "never bend it" not in close
    assert "never bend it" in loose and "tell it now" not in loose
