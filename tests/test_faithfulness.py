"""Faithfulness labels on the three cases from the design notes."""

from faithfulness import check, cited_references
from scripture import Passage

MATTHEW_11 = Passage(0, "Matthew", 11, (28, 29), (
    "Come to Me, all you who are weary and burdened, and I will give you rest.",
    "Take My yoke upon you and learn from Me; for I am gentle and humble in heart, "
    "and you will find rest for your souls.",
))


def test_verbatim_quote_with_a_short_bridge_is_grounded():
    result = check("My child. Come to Me, all you who are weary and burdened, and I will give "
                   "you rest. Matthew 11:28.", [MATTHEW_11])
    kinds = [s["kind"] for s in result["sentences"]]
    assert kinds == ["own", "verbatim"]
    assert result["citations"] == [{"ref": "Matthew 11:28", "supported": True}]
    assert result["paraphrased"] == 0 and result["unsupported_citations"] == 0
    assert result["grounded_share"] > 0.8


def test_half_a_verse_word_for_word_still_counts_as_verbatim():
    result = check("I am gentle and humble in heart.", [MATTHEW_11])
    assert result["sentences"][0]["kind"] == "verbatim"
    assert result["sentences"][0]["ref"] == "Matthew 11:29"


def test_swapping_rest_for_peace_is_flagged_as_a_paraphrase():
    result = check("Come to me, all who are tired, and I will give you peace.", [MATTHEW_11])
    assert result["sentences"][0]["kind"] == "paraphrased"
    assert result["paraphrased"] == 1
    assert result["grounded_share"] == 0


def test_one_swapped_word_at_the_end_is_not_verbatim():
    result = check("Come to Me, all you who are weary and burdened, and I will give you peace.",
                   [MATTHEW_11])
    sentence = result["sentences"][0]
    assert sentence["kind"] == "paraphrased" and sentence["changed_words"] == 1


def test_a_quote_running_across_two_verses_is_checked_as_one_stretch():
    result = check("I will give you rest. Take My yoke upon you and learn from Me, for I am gentle "
                   "and humble in heart.", [MATTHEW_11])
    assert [s["kind"] for s in result["sentences"]] == ["verbatim", "verbatim"]
    assert result["sentences"][1]["ref"] == "Matthew 11:29"
    joined = check("and I will give you rest Take My yoke upon you", [MATTHEW_11])
    assert joined["sentences"][0]["ref"] == "Matthew 11:28-29"


def test_an_ellipsis_is_an_honest_omission():
    result = check("Come to Me, all you who are weary… and you will find rest for your souls.",
                   [MATTHEW_11])
    assert [s["kind"] for s in result["sentences"]] == ["verbatim", "verbatim"]


def test_a_few_common_words_in_common_are_not_a_quote():
    result = check("Yes, I am here with you.", [MATTHEW_11])
    assert result["sentences"][0]["kind"] == "own"


def test_a_reference_that_was_never_retrieved_is_unsupported():
    result = check("As it is written in John 8:12, I am the light of the world.", [MATTHEW_11])
    assert result["citations"] == [{"ref": "John 8:12", "supported": False}]
    assert result["unsupported_citations"] == 1


MATTHEW_18 = Passage(1, "Matthew", 18, (16,), (
    "But if he will not listen, take one or two others along, so that ‘every matter may be "
    "established by the testimony of two or three witnesses.’",
))
LUKE_17 = Passage(2, "Luke", 17, (3,), (
    "Watch yourselves. If your brother sins, rebuke him; and if he repents, forgive him.",
))


def test_a_quote_spliced_under_another_reference_is_misattributed():
    result = check("If your brother sins, rebuke him; and if he repents, forgive him. But if he will "
                   "not listen, take one or two others along… (Luke 17:3-4).", [LUKE_17, MATTHEW_18])
    assert [s["kind"] for s in result["sentences"]] == ["verbatim", "verbatim", "verbatim"]
    assert result["unsupported_citations"] == 0
    assert result["misattributed_quotes"] == 1
    assert result["sentences"][2]["ref"] == "Matthew 18:16"


def test_a_reference_covers_only_its_own_paragraph():
    # The unreferenced Luke quote is uncited, not misattributed to the Matthew reference.
    result = check("If your brother sins, rebuke him.\n\nMatthew 18:16 says: But if he will not "
                   "listen, take one or two others along.", [LUKE_17, MATTHEW_18])
    assert result["uncited_quotes"] == 1 and result["misattributed_quotes"] == 0


def test_a_saying_found_in_two_gospels_follows_the_cited_one():
    matthew = Passage(3, "Matthew", 22, (21,), (
        "“Caesar’s,” they answered. So Jesus told them, “Give to Caesar what is "
        "Caesar’s, and to God what is God’s.”",))
    mark = Passage(4, "Mark", 12, (17,), (
        "Then Jesus told them, “Give to Caesar what is Caesar’s, and to God what is God’s.” "
        "And they marveled at Him.",))
    result = check("Give to Caesar what is Caesar’s, and to God what is God’s. Matthew 22:21.",
                   [mark, matthew])
    assert result["sentences"][0]["ref"] == "Matthew 22:21"
    assert result["misattributed_quotes"] == 0


def test_a_phrase_repeated_in_one_passage_aligns_with_the_cited_verse():
    john_4 = Passage(7, "John", 4, (7, 13), (
        "When a Samaritan woman came to draw water, Jesus said to her, “Give Me a drink.”",
        "Jesus said to her, “Everyone who drinks this water will be thirsty again.”",
    ))
    result = check("John 4:13: Jesus said to her, “Everyone who drinks this water will be thirsty again.”",
                   [john_4])
    assert result["misattributed_quotes"] == 0
    assert {s["ref"] for s in result["sentences"] if s["kind"] != "own"} == {"John 4:13"}


def test_a_quote_without_any_reference_is_uncited():
    result = check("Come to Me, all you who are weary and burdened.", [MATTHEW_11])
    assert result["uncited_quotes"] == 1 and result["misattributed_quotes"] == 0


def test_reference_forms():
    assert cited_references("Luke chapter 15, verse 4 and Mark 2:23-28") == [
        ("Luke", 15, 4, 4), ("Mark", 2, 23, 28)]
    assert cited_references("matthew 6:25 – 34") == [("Matthew", 6, 25, 34)]
