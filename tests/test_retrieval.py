"""Scored retrieval across the three strategies."""

import math

import pytest

from app.index.retrieval import _sigmoid, compare, retrieve


def test_sigmoid_maps_logits_into_0_1():
    assert _sigmoid(0.0) == pytest.approx(0.5)
    assert 0.0 <= _sigmoid(-800.0) <= 1.0   # must not overflow
    assert 0.0 <= _sigmoid(800.0) <= 1.0
    assert _sigmoid(-5) < _sigmoid(0) < _sigmoid(5)


@pytest.mark.parametrize("engine", ["auto", "bm25", "rerank"])
def test_every_strategy_returns_normalised_scores(make_workspace, engine):
    ws = make_workspace()
    # A query sharing a literal term with the corpus, so BM25 also matches.
    result = retrieve(ws.collection_name, ws.index_version, "install crawl4ai", engine, 3)

    assert result.error is None
    assert result.results, f"{engine} returned nothing"
    for chunk in result.results:
        assert 0.0 <= chunk.score <= 1.0, f"{engine} score out of range: {chunk.score}"
        assert chunk.source_url.startswith("https://")
    # Ranks are 1-based and ordered.
    assert [c.rank for c in result.results] == list(range(1, len(result.results) + 1))


def test_vector_scores_are_clamped_into_range(make_workspace):
    """Chroma cosine relevance can go slightly negative; it must not leak out."""
    ws = make_workspace()
    result = retrieve(
        ws.collection_name, ws.index_version, "completely unrelated zebra topic", "auto", 3
    )
    assert result.error is None
    assert all(0.0 <= c.score <= 1.0 for c in result.results)


def test_bm25_returns_nothing_when_no_keyword_matches(make_workspace):
    """No lexical overlap is an empty result, not an error and not noise."""
    ws = make_workspace()
    result = retrieve(
        ws.collection_name, ws.index_version, "zebra xylophone quixotic", "bm25", 3
    )
    assert result.error is None
    assert result.results == []


def test_unknown_engine_is_rejected(make_workspace):
    ws = make_workspace()
    with pytest.raises(ValueError, match="Unsupported query engine"):
        retrieve(ws.collection_name, ws.index_version, "q", "nope", 3)


def test_empty_collection_reports_error_instead_of_crashing(make_workspace):
    from app.services import workspaces as svc

    ws = svc.create_workspace(seed_url="https://empty.dev", name="Empty")
    result = retrieve(ws.collection_name, ws.index_version, "anything", "bm25", 3)
    assert result.results == []
    assert result.error and "empty" in result.error.lower()


def test_compare_runs_all_three_and_reports_pairwise_overlap(make_workspace):
    ws = make_workspace()
    out = compare(ws.collection_name, ws.index_version, "install", 3)

    assert set(out["strategies"]) == {"auto", "bm25", "rerank"}
    pairwise = out["overlap"]["pairwise"]
    assert set(pairwise) == {"auto|bm25", "auto|rerank", "bm25|rerank"}
    for stats in pairwise.values():
        assert 0.0 <= stats["jaccard"] <= 1.0
        assert stats["shared_count"] >= 0
