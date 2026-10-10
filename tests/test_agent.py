"""The v6 agent: routing, the definitions tool, the scope check and the graph's control flow."""

import json

import pytest

from statnav.agent import graph as agent_graph
from statnav.agent.router import route, scope
from statnav.agent.tools import Definitions
from statnav.answer import SYSTEM_PROMPT
from statnav.llm.client import Reply
from statnav.retrieve.amend import render
from statnav.retrieve.dense import Hit


@pytest.mark.parametrize("question,has_term,expected", [
    ("How was section 99(2) amended by the Finance Act, 2026?", False, "amendment"),
    ('What is the meaning of "transfer" under the Income-tax Act, 2025?', True, "definition"),
    ('What is the meaning of "widget" under the Act?', False, "general"),
    ("Under section 393, what is the TDS rate on insurance commission?", False, "table"),
    ("When must a return of income be furnished?", False, "general"),
    # "amended" without a provision to look up is not an amendment lookup
    ("Which provisions were amended in 2026?", False, "general"),
])
def test_route(question, has_term, expected):
    assert route(question, has_term) == expected


DEFS = Definitions.from_rows([
    ("s2(109)", '"transfer" in relation to a capital asset, includes— where,'),
    ("s98(a)", '"transfer" means a transfer of an asset by way of gift;'),
    ("s2(5)", '"agricultural income" means— but shall not include—'),
    ("s2(49)", '"income" includes—'),
    ("s2(82)", '"Principal Commissioner" means a person appointed to be a Principal '
               "Commissioner of Income-tax under section 237(1);"),
    ("s2(50)", '"income-tax" means the tax charged under this Act;'),
    ("s66(40)", '"University" means a University established by law;'),
    ("s402(44)", '"University" shall have the meaning assigned to it in section 66(40);'),
    ("s2(10)", "the text of a clause that defines nothing"),
])


def test_definitions_index_prefers_section_2():
    assert DEFS.terms["transfer"] == ["s2(109)", "s98(a)"]
    assert "s2(10)" not in {p for ps in DEFS.terms.values() for p in ps}


def test_find_a_quoted_term_takes_one_provision():
    assert DEFS.find('What is the meaning of "transfer" under the Income-tax Act, 2025?') == [
        ("transfer", ["s2(109)"])]


def test_find_unquoted_takes_only_the_longest_term():
    got = DEFS.find("What is the definition of a Principal Commissioner of Income-tax?")
    assert got == [("principal commissioner", ["s2(82)"])]
    assert DEFS.find("How is agricultural income defined?") == [
        ("agricultural income", ["s2(5)"])]


def test_find_ignores_the_acts_own_name():
    assert DEFS.find("What does the Income-tax Act, 2025 say about salaries?") == []


def test_find_prefers_a_definition_in_the_named_section():
    got = DEFS.find('What is the definition of a "University" as used in section 66(40)?')
    assert got == [("university", ["s66(40)"])]


def test_render_raw_endnote_matches_the_oracle_shape():
    assert render("11", 'Sub. for "x" by Act No. 4 of 2026.', None) == (
        'Endnote 11: Sub. for "x" by Act No. 4 of 2026.')


def test_render_structured_endnote_states_target_and_change_type():
    line = render("52", "Ins. by Act No. 4 of 2026, w.e.f. 1-4-2026.", None, "inserted",
                  "Act No. 4 of 2026", "1-4-2026", "Schedule XIV, paragraph 4(3)")
    assert line.startswith("Endnote 52 [applies to Schedule XIV, paragraph 4(3); amendment "
                           "type: inserted; by Act No. 4 of 2026; with effect from 1-4-2026]: "
                           "Ins. by")


class FakeLLM:
    """Stands in for ChatClient: returns canned replies and records what it was sent."""

    def __init__(self, *texts: str) -> None:
        self.texts = list(texts)
        self.calls: list[list[dict]] = []

    def chat(self, messages, json_mode=False, max_tokens=None):  # noqa: ARG002
        self.calls.append(messages)
        return Reply(self.texts.pop(0), {"total_tokens": 42}, "fake", False, 0.1)

    def chat_stream(self, messages, on_delta, max_tokens=None):  # noqa: ARG002
        """Streams the canned reply in 7-character pieces; `streamed` counts these calls."""
        self.streamed = getattr(self, "streamed", 0) + 1
        self.calls.append(messages)
        text = self.texts.pop(0)
        for i in range(0, len(text), 7):
            on_delta(text[i:i + 7])
        return Reply(text, {"total_tokens": 42}, "fake", False, 0.1)


def test_scope_reads_the_verdict():
    v = scope(FakeLLM('{"in_scope": false, "reason": "asks about the e-filing portal"}'), "q")
    assert (v.in_scope, v.reason, v.tokens) == (False, "asks about the e-filing portal", 42)


def test_scope_fails_open_on_an_unparseable_reply():
    assert scope(FakeLLM("no idea"), "q").in_scope is True


CFG = {"chunks": "v2", "retrieval": {"mode": "hybrid", "k": 10}, "evidence_budget": 100,
       "agent": {"scope_check": True, "definitions": False}}


@pytest.fixture
def fake_retrieval(monkeypatch):
    hits = [Hit("v2:s1", "s1", 0.9, "Section 1 text", 30, 1, 1, {"provisions": ["s1"]}),
            Hit("v2:s2", "s2", 0.8, "Section 2 text", 90, 2, 2, {"provisions": ["s2"]})]
    calls = []

    def retrieve(conn, jina, question, cfg, k=None):  # noqa: ARG001
        calls.append(question)
        return hits

    monkeypatch.setattr(agent_graph, "retrieve", retrieve)
    return calls


def test_out_of_scope_is_refused_before_retrieval(fake_retrieval):
    answer = FakeLLM()
    agent = agent_graph.Agent(None, None, CFG, answer,
                              FakeLLM('{"in_scope": false, "reason": "a CBDT circular"}'))
    r = agent.run("What did CBDT Circular No. 1 of 2026 clarify?")
    assert r.steps == ["classify", "refuse"]
    assert r.out["refused"] and "CBDT circular" in r.out["answer"]
    assert r.reply is None and r.evidence == [] and fake_retrieval == [] and answer.calls == []


def test_in_scope_retrieves_packs_and_generates(fake_retrieval):
    answer = FakeLLM(json.dumps({"answer": "It says X.", "citations": ["C1"], "refused": False}))
    agent = agent_graph.Agent(None, None, CFG, answer, FakeLLM('{"in_scope": true}'))
    r = agent.run("What does section 1 say?")
    assert r.steps == ["classify", "retrieve", "pack", "generate"]
    # the 90-token hit does not fit beside the 30-token one in a 100-token budget
    assert [h["chunk_id"] for h in r.evidence] == ["v2:s1"]
    assert r.out["answer"] == "It says X." and r.classify_tokens == 42


def test_explained_style_uses_the_route_block(fake_retrieval):
    cfg = {**CFG, "generation": {"prompt": "explained", "role": "answer_explained"}}
    answer = FakeLLM(json.dumps({"answer": "### In short\nIt changed [C1].", "citations": [],
                                 "follow_ups": ["What does section 1 say?"], "refused": False}))
    agent = agent_graph.Agent(None, None, cfg, answer, FakeLLM('{"in_scope": true}'))
    r = agent.run("How was section 1 amended by the Finance Act, 2026?")
    system = answer.calls[0][0]["content"]
    assert r.route == "amendment" and "### What changed" in system
    assert "### Conditions to check" not in system


def test_basic_style_keeps_the_measured_prompt(fake_retrieval):
    answer = FakeLLM(json.dumps({"answer": "It says X.", "citations": ["C1"], "refused": False}))
    agent = agent_graph.Agent(None, None, CFG, answer, FakeLLM('{"in_scope": true}'))
    agent.run("How was section 1 amended by the Finance Act, 2026?")
    assert answer.calls[0][0]["content"] == SYSTEM_PROMPT


def test_retrieval_only_stops_after_packing(fake_retrieval):
    agent = agent_graph.Agent(None, None, CFG, None, FakeLLM('{"in_scope": true}'))
    r = agent.run("What does section 1 say?", generate=False)
    assert r.steps == ["classify", "retrieve", "pack"] and r.out is None


# -- v7 verifier -------------------------------------------------------------------------
from statnav.agent.verify import verify  # noqa: E402

V_CFG = {**CFG, "agent": {"scope_check": True, "definitions": False, "verify": True},
         "evidence_budget": 200}
ANSWER = json.dumps({"answer": "It says X within 30 days.", "citations": ["C1"],
                     "refused": False})


def test_verify_rederives_citations_from_support():
    v = verify(FakeLLM('{"claims": [{"claim": "X", "support": ["C2", "[C1]"]},'
                       ' {"claim": "30 days", "support": ["C2"]}]}'), "a", "ev", 2)
    assert v.ok and v.citations == ["C1", "C2"] and v.unsupported == []


def test_verify_flags_unsupported_and_ignores_out_of_range_labels():
    v = verify(FakeLLM('{"claims": [{"claim": "X", "support": ["C9"]}]}'), "a", "ev", 2)
    assert not v.ok and v.unsupported == ["X"] and v.citations == []


@pytest.mark.parametrize("reply", ["not json", '{"claims": []}'])
def test_verify_fails_open(reply):
    v = verify(FakeLLM(reply), "a", "ev", 2)
    assert v.ok and v.error


@pytest.mark.parametrize("rederive,cites", [(False, ["C1"]), (True, ["C1", "C2"])])
def test_supported_answer_is_verified_once(fake_retrieval, rederive, cites):
    cfg = {**V_CFG, "agent": {**V_CFG["agent"], "verify_citations": rederive}}
    answer = FakeLLM(ANSWER)
    checker = FakeLLM('{"claims": [{"claim": "X", "support": ["C1", "C2"]}]}')
    r = agent_graph.Agent(None, None, cfg, answer, FakeLLM('{"in_scope": true}'),
                          checker).run("What does section 1 say?")
    assert r.steps[-2:] == ["generate", "verify"] and r.attempts == 1 and r.verified
    # the generator's own citations stand unless re-derivation is switched on
    assert r.out["citations"] == cites and r.answer_tokens == 42


def test_unsupported_claim_gets_one_retry_naming_it(fake_retrieval):
    answer = FakeLLM(ANSWER, ANSWER)
    checker = FakeLLM('{"claims": [{"claim": "30 days", "support": []}]}',
                      '{"claims": [{"claim": "30 days", "support": []}]}')
    r = agent_graph.Agent(None, None, V_CFG, answer, FakeLLM('{"in_scope": true}'),
                          checker).run("What does section 1 say?")
    assert r.steps[-4:] == ["generate", "verify", "generate", "verify"]
    assert r.attempts == 2 and r.verified is False and r.unsupported == ["30 days"]
    retry_msgs = answer.calls[1]
    assert retry_msgs[2]["role"] == "assistant" and "- 30 days" in retry_msgs[3]["content"]
    assert r.answer_tokens == 84 and r.verify_tokens == 84


def test_refused_answer_is_not_verified(fake_retrieval):
    checker = FakeLLM()
    r = agent_graph.Agent(None, None, V_CFG,
                          FakeLLM('{"answer": "Not in the passages.", "citations": [],'
                                  ' "refused": true}'),
                          FakeLLM('{"in_scope": true}'), checker).run("q")
    assert "verify" not in r.steps and checker.calls == []
