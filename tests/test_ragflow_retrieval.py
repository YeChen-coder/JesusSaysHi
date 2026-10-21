"""RAGFlow adapter offline: parsing sections back, dedup, abstention, filters, traces."""

import json

import pytest

from ragflow_retrieval import RagflowIndex, chunk_passages

SECTION = ("Matthew 11:25-30 · Rest for the Weary\n"
           "Parallel accounts: Luke 10:21–24\n"
           "Matthew 11:28 Come to Me, all you who are weary and burdened, and I will give you rest.\n"
           "Matthew 11:29 Take My yoke upon you and learn from Me.\n")
CROSSING = ("Matthew 4:23-5:1 · Jesus Heals the Sick\n"
            "Matthew 4:25 Large crowds followed Him.\n"
            "Matthew 5:1 When Jesus saw the crowds, He went up on the mountain.\n")


class FakeClient:
    def __init__(self, chunks):
        self.chunks = chunks
        self.calls = []

    def retrieve(self, question, dataset_ids, **params):
        self.calls.append((question, dataset_ids, params))
        return {"chunks": self.chunks}


def chunk(doc, score, content=SECTION):
    return {"document_id": doc, "document_keyword": f"{doc}.txt", "similarity": score,
            "term_similarity": score / 2, "vector_similarity": score, "content": content}


@pytest.fixture
def index_with(tmp_path, monkeypatch):
    monkeypatch.setattr("ragflow_retrieval.make_passages", lambda verses: [])
    monkeypatch.setattr("ragflow_retrieval.read_verses", lambda path: [])

    def build(chunks, **kwargs):
        return RagflowIndex(FakeClient(chunks), ["ds"], trace_path=tmp_path / "trace.jsonl", **kwargs)
    return build


def test_sections_split_back_into_passages_per_chapter():
    [rest] = chunk_passages(SECTION)
    assert rest.ref == "Matthew 11:28-29" and rest.title == "Rest for the Weary"
    assert rest.texts[0].startswith("Come to Me")
    crossing = chunk_passages(CROSSING)
    assert [p.ref for p in crossing] == ["Matthew 4:25", "Matthew 5:1"]


def test_one_result_per_section_best_first(index_with):
    index = index_with([chunk("a", .9), chunk("a", .8), chunk("b", .7, CROSSING)])
    assert [c["document_id"] for c in index.retrieve("rest", 3)] == ["a", "b"]
    assert [p.ref for p in index.search("rest", 3)] == ["Matthew 11:28-29", "Matthew 4:25", "Matthew 5:1"]


def test_abstains_below_the_threshold_and_traces_it(index_with, tmp_path):
    index = index_with([chunk("a", .2)], min_score=0.35)
    assert index.search("weather in Chicago") == []
    trace = json.loads((tmp_path / "trace.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert trace["abstained"] is True and trace["candidates"][0]["score"] == 0.2


def test_a_failing_reranker_falls_back_to_the_hybrid_ranking(index_with, tmp_path):
    from ragflow_client import RagflowError

    index = index_with([chunk("a", .9)], rerank_id="rerank-2.5@default@Voyage AI")
    original = index.client.retrieve

    def rate_limited(question, dataset_ids, **params):
        if "rerank_id" in params:
            raise RagflowError("retrieval search failed: Voyage rerank API error: 429 Too Many Requests")
        return original(question, dataset_ids, **params)

    index.client.retrieve = rate_limited
    assert [c["document_id"] for c in index.retrieve("rest")] == ["a"]
    trace = json.loads((tmp_path / "trace.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert "429" in trace["rerank_fallback"]


def test_rerank_and_red_letter_filter_reach_ragflow(index_with):
    index = index_with([chunk("a", .9)], rerank_id="rerank-2.5@Voyage AI", keyword_weight=0.3)
    index.retrieve("rest", 3, jesus_only=True)
    _, datasets, params = index.client.calls[-1]
    assert datasets == ["ds"] and params["rerank_id"] == "rerank-2.5@Voyage AI"
    assert params["keywords_similarity_weight"] == 0.3
    assert params["metadata_condition"]["conditions"][0] == {
        "name": "jesus_speaks", "comparison_operator": "=", "value": "yes"}
    assert "min_score" not in params
