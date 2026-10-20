"""Lexical scoring, rank fusion, overlap removal and the eval metrics, all offline."""

import numpy as np

from evaluate import first_hit, summarize
from retrieval import BM25, ScriptureIndex, distinct, rrf, tokenize
from scripture import Passage


def passage(pid, chapter, verses, text):
    return Passage(pid, "Matthew", chapter, tuple(verses), tuple([text] + [""] * (len(verses) - 1)))


def test_tokenize_folds_inflections_and_drops_stopwords():
    assert tokenize("Do not worry; they worried about worries") == ["worry", "worry", "worry"]
    assert tokenize("Don’t") == ["don"]


def test_bm25_prefers_the_document_that_shares_rare_terms():
    bm25 = BM25(["the sparrow falls", "bread and fish", "bread and wine and bread"])
    scores = bm25.scores("sparrows")
    assert int(np.argmax(scores)) == 0
    assert scores[1] == 0


def test_rrf_rewards_agreement_between_rankings():
    assert rrf([[1, 2, 3], [2, 3, 1]])[0] == 2
    assert rrf([[5, 6], [6, 7]])[0] == 6


def test_distinct_skips_windows_that_overlap_a_chosen_one():
    passages = [passage(0, 6, [25, 26, 27], "a"), passage(1, 6, [27, 28, 29], "b"),
                passage(2, 7, [1, 2], "c")]
    assert [p.id for p in distinct(passages, [0, 1, 2], 2)] == [0, 2]


def test_index_modes_use_the_embedding_and_the_lexical_side():
    passages = [passage(0, 1, [1], "storm on the sea"), passage(1, 2, [1], "lilies of the field")]
    embeddings = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    index = ScriptureIndex(passages, embeddings, lambda texts: np.array([[0.0, 1.0]], dtype=np.float32))
    assert index.rank("storm", "bm25")[0] == 0
    assert index.rank("storm", "dense")[0] == 1
    assert sorted(p.id for p in index.search("storm", 2, "hybrid")) == [0, 1]


def test_first_hit_and_summary():
    passages = [passage(0, 6, [1, 2], "a"), passage(1, 6, [25, 26], "b")]
    assert first_hit(passages, {("Matthew", 6, 26)}) == 2
    assert first_hit(passages, {("Matthew", 7, 1)}) is None
    row = summarize([1, 2, None, 4])
    assert row["hit@1"] == 0.25 and row["hit@3"] == 0.5 and row["hit@5"] == 0.75
    assert abs(row["mrr"] - (1 + 0.5 + 0.25) / 4) < 1e-9
