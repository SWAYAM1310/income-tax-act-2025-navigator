"""Jina client behaviour against a mocked HTTP transport (no network, no tokens spent)."""

import json

import httpx
import numpy as np
import pytest

from statnav.embed.jina import JinaClient, JinaError


def make_client(tmp_path, handler):
    return JinaClient.from_config(cache_path=tmp_path / "jina.sqlite",
                                  transport=httpx.MockTransport(handler))


def fake_embeddings(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    data = [{"index": i, "embedding": [float(len(t)), 1.0] + [0.0] * 1022}
            for i, t in enumerate(body["input"])]
    return httpx.Response(200, json={"data": data, "usage": {"total_tokens": 7 * len(data)}})


def test_embed_batches_caches_and_dedupes(tmp_path):
    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        return fake_embeddings(request)

    jc = make_client(tmp_path, handler)
    jc.batch_size = 2
    texts = ["alpha", "beta", "alpha", "gamma"]
    vecs = jc.embed(texts, task="retrieval.passage")
    assert vecs.shape == (4, 1024)
    assert np.allclose(vecs[0], vecs[2])  # duplicate text, same vector
    assert [len(c["input"]) for c in calls] == [2, 1]  # 3 unique texts in batches of 2
    assert calls[0]["task"] == "retrieval.passage" and calls[0]["dimensions"] == 1024
    assert jc.usage.tokens == 21

    again = make_client(tmp_path, handler)  # new process, same on-disk cache
    vecs2 = again.embed(texts, task="retrieval.passage")
    assert len(calls) == 2 and np.allclose(vecs, vecs2)
    assert again.usage.tokens == 0 and again.usage.cache_hits == 4


def test_query_and_passage_embeddings_are_cached_separately(tmp_path):
    seen = []

    def handler(request):
        seen.append(json.loads(request.content)["task"])
        return fake_embeddings(request)

    jc = make_client(tmp_path, handler)
    jc.embed(["agricultural income"], task="retrieval.passage")
    jc.embed_query("agricultural income")
    assert seen == ["retrieval.passage", "retrieval.query"]


def test_rerank_is_cached(tmp_path):
    calls = []

    def handler(request):
        calls.append(request.url.path)
        body = json.loads(request.content)
        results = [{"index": i, "relevance_score": 1.0 / (i + 1)}
                   for i in range(len(body["documents"]))]
        return httpx.Response(200, json={"results": results, "usage": {"total_tokens": 50}})

    jc = make_client(tmp_path, handler)
    first = jc.rerank("q", ["d1", "d2", "d3"], top_n=2)
    second = jc.rerank("q", ["d1", "d2", "d3"], top_n=2)
    assert [r["index"] for r in first] == [0, 1] and first == second
    assert calls == ["/v1/rerank"]


def test_auth_error_is_not_retried(tmp_path):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(401, json={"detail": "invalid key"})

    jc = make_client(tmp_path, handler)
    with pytest.raises(JinaError):
        jc.embed(["x"], task="retrieval.passage")
    assert len(calls) == 1
