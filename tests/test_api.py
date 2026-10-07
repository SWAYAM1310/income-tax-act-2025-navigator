"""The HTTP API: streamed answers (fake LLMs, no tokens), lookups (database), eval summaries."""

import json

import pytest
from fastapi.testclient import TestClient
from tests.test_agent import CFG, FakeLLM

from statnav.agent import graph as agent_graph
from statnav.api.app import Services, create_app
from statnav.llm.client import QuotaExhausted
from statnav.retrieve.dense import Hit


def events(body: str) -> list[tuple[str, object]]:
    out = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        out.append((lines["event"], json.loads(lines["data"])))
    return out


class FakeBot:
    def __init__(self, agent):
        self.agent = agent


@pytest.fixture
def hits(monkeypatch):
    found = [Hit("v2:s1", "s1", 0.9, "Section 1 text", 30, 4, 4, {"provisions": ["s1"]})]
    monkeypatch.setattr(agent_graph, "retrieve", lambda *a, **k: found)


def client_with(answer_llm, classify_llm) -> TestClient:
    def make(version):
        return FakeBot(agent_graph.Agent(None, None, CFG, answer_llm, classify_llm))
    return TestClient(create_app(Services(answerer=make, connect=lambda: None)))


def test_health():
    r = client_with(FakeLLM(), FakeLLM()).get("/health")
    assert r.status_code == 200 and r.json()["default_version"] == "v8"
    assert "v8" in r.json()["versions"] and "oracle" not in r.json()["versions"]


def test_query_streams_steps_evidence_and_a_cited_answer(hits):
    answer = FakeLLM(json.dumps({"answer": "Section 1 says X.", "citations": ["C1"],
                                 "refused": False}))
    r = client_with(answer, FakeLLM('{"in_scope": true}')).post(
        "/query", json={"question": "What does section 1 say?"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    ev = events(r.text)
    kinds = [e for e, _ in ev]
    n = kinds.count("token")
    # evidence as soon as it is packed, then the answer text as it is written
    assert n > 1 and kinds == (["step"] * 4 + ["evidence"] + ["token"] * n
                               + ["step", "evidence", "answer", "done"])
    # every graph node reports, including `tools` when it has nothing to add
    assert [d["node"] for e, d in ev if e == "step"] == ["classify", "retrieve", "tools", "pack",
                                                         "generate"]
    assert ev[0][1]["in_scope"] is True and ev[4][1][0]["label"] == "C1"
    streamed = "".join(d["text"] for e, d in ev if e == "token")
    assert streamed == "Section 1 says X." and {d["attempt"] for e, d in ev if e == "token"} == {1}
    ans = dict(ev)["answer"]
    assert ans["answer"] == "Section 1 says X." and not ans["refused"]
    assert ans["citations"] == [{"chunk_id": "v2:s1", "provisions": ["s1"], "page_start": 4,
                                 "page_end": 4}]


def test_the_eval_path_never_streams(hits):
    answer = FakeLLM(json.dumps({"answer": "X.", "citations": ["C1"], "refused": False}))
    agent = agent_graph.Agent(None, None, CFG, answer, FakeLLM('{"in_scope": true}'))
    assert agent.run("What does section 1 say?").out["answer"] == "X."
    assert not getattr(answer, "streamed", 0)


def test_a_stream_that_fails_falls_back_to_the_measured_call(hits):
    from statnav.llm.client import LLMError

    class Broken(FakeLLM):
        def chat_stream(self, *a, **k):
            raise LLMError("stream refused")

    answer = Broken(json.dumps({"answer": "Y.", "citations": ["C1"], "refused": False}))
    r = client_with(answer, FakeLLM('{"in_scope": true}')).post(
        "/query", json={"question": "What does section 1 say?"})
    ev = events(r.text)
    assert "token" not in [e for e, _ in ev] and dict(ev)["answer"]["answer"] == "Y."


def test_out_of_scope_question_is_refused_without_evidence(hits):
    answer = FakeLLM()
    r = client_with(answer, FakeLLM('{"in_scope": false, "reason": "a CBDT circular"}')).post(
        "/query", json={"question": "What did CBDT Circular No. 1 of 2026 clarify?"})
    ev = dict(events(r.text))
    assert ev["answer"]["refused"] and "CBDT circular" in ev["answer"]["answer"]
    assert ev["evidence"] == [] and answer.calls == []


def test_quota_exhaustion_is_an_error_event_not_an_answer(hits):
    class Exhausted(FakeLLM):
        def chat(self, *a, **k):
            raise QuotaExhausted("openai/gpt-oss-120b: provider says retry after 900s")

        chat_stream = chat

    r = client_with(Exhausted(), FakeLLM('{"in_scope": true}')).post(
        "/query", json={"question": "What does section 1 say?"})
    ev = dict(events(r.text))
    assert "retry after 900s" in ev["error"]["message"]
    assert ev["answer"]["error"] and not ev["answer"]["refused"]


@pytest.mark.parametrize("body", [{"question": "hi"}, {"question": "What is X?", "version": "v9"},
                                  {"question": "What is X?", "k": 0}])
def test_query_validates_its_input(body):
    assert client_with(FakeLLM(), FakeLLM()).post("/query", json=body).status_code == 422


def test_evals_summarises_the_committed_results():
    r = client_with(FakeLLM(), FakeLLM()).get("/evals", params={"split": "dev_mini"})
    rows = {x["version"]: x for x in r.json()["versions"]}
    assert rows["v6"]["complete"] and rows["v6"]["n"] == 30
    assert 0 < rows["v6"]["metrics"]["fact_recall"] <= 1
    assert list(rows)[-1] == "oracle"


@pytest.fixture(scope="module")
def db_client():
    from statnav.index.db import connect
    try:
        connect().close()
    except Exception as exc:  # noqa: BLE001 - any connection failure means "skip"
        pytest.skip(f"database not reachable: {exc}")
    return TestClient(create_app(Services(answerer=lambda v: None,
                                          connect=lambda: connect(autocommit=True))))


@pytest.mark.db
def test_provision_lookup(db_client):
    p = db_client.get("/provisions/s2(5)").json()
    assert p["citation"] == "section 2(5)" and [c["id"] for c in p["children"]][:2] == [
        "s2(5)(a)", "s2(5)(b)"]
    assert db_client.get("/provisions/no-such-id").status_code == 404


@pytest.mark.db
def test_table_rows_and_amendments(db_client):
    rows = db_client.get("/tables/s393:tbl1/rows", params={"sl_no": "1"}).json()
    assert [r["row_id"] for r in rows] == ["s393:tbl1#1(i)", "s393:tbl1#1(ii)"]
    assert db_client.get("/tables/s393:tbl1/rows", params={"sl_no": "999"}).status_code == 404
    notes = db_client.get("/amendments/sch:XIV:4").json()
    assert {(a["applies_to"], a["type"]) for a in notes} == {
        ("Schedule XIV, paragraph 4(1)(a)", "substituted"),
        ("Schedule XIV, paragraph 4(3)", "inserted")}
