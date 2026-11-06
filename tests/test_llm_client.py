import json
import os
import subprocess
import sys
from unittest.mock import MagicMock

import httpx
import pytest
from langsmith import Client
from langsmith.run_helpers import get_current_run_tree, tracing_context

from statnav.config import ROOT
from statnav.llm.client import ChatClient, QuotaExhausted, _Window


@pytest.fixture(autouse=True)
def fresh_rate_window(monkeypatch):
    """Each test gets its own limiter: the shared one would really wait out the minute."""
    monkeypatch.setattr("statnav.llm.client._windows", {})


def handler_factory(calls):
    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        return httpx.Response(200, json={
            "choices": [{"message": {"content": '{"answer": "ok"}'}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25}})
    return handler


def test_chat_is_cached_and_counted(tmp_path):
    calls = []
    llm = ChatClient("answer", transport=httpx.MockTransport(handler_factory(calls)),
                     store_path=tmp_path / "llm.sqlite")
    msgs = [{"role": "user", "content": "hello"}]
    r1 = llm.chat(msgs, json_mode=True)
    r2 = llm.chat(msgs, json_mode=True)
    assert r1.json() == {"answer": "ok"} and not r1.cached and r2.cached
    assert len(calls) == 1
    assert calls[0]["temperature"] == 0 and calls[0]["response_format"] == {"type": "json_object"}
    assert calls[0]["reasoning_effort"] == "low"
    assert llm.spent_today() == 25


def test_daily_quota_guard(tmp_path):
    calls = []
    llm = ChatClient("answer", transport=httpx.MockTransport(handler_factory(calls)),
                     store_path=tmp_path / "llm.sqlite")
    llm.store.add(llm.model, llm.tokens_per_day - 10)
    with pytest.raises(QuotaExhausted):
        llm.chat([{"role": "user", "content": "x" * 50}])
    assert calls == []


def sse(*chunks: dict) -> bytes:
    return "".join(f"data: {json.dumps(c)}\n\n" for c in chunks).encode() + b"data: [DONE]\n\n"


def stream_handler(calls, status=200, headers=None):
    def handler(request):
        calls.append(json.loads(request.content))
        if status != 200:
            return httpx.Response(status, headers=headers or {}, text="slow down")
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=sse(
            {"choices": [{"delta": {"reasoning": "thinking..."}}]},
            {"choices": [{"delta": {"content": '{"answer": '}}]},
            {"choices": [{"delta": {"content": '"ok"}'}, "finish_reason": "stop"}],
             "x_groq": {"usage": {"prompt_tokens": 20, "completion_tokens": 5,
                                  "total_tokens": 25}}}))
    return handler


def test_chat_stream_forwards_text_then_replays_it_from_its_own_cache(tmp_path):
    calls, got = [], []
    llm = ChatClient("answer", transport=httpx.MockTransport(stream_handler(calls)),
                     store_path=tmp_path / "llm.sqlite")
    msgs = [{"role": "user", "content": "hello"}]
    r1 = llm.chat_stream(msgs, got.append)
    assert got == ['{"answer": ', '"ok"}'] and r1.json() == {"answer": "ok"} and not r1.cached
    assert calls[0]["stream"] is True and "response_format" not in calls[0]
    assert llm.spent_today() == 25
    replayed = []
    r2 = llm.chat_stream(msgs, replayed.append, replay_pause=0)
    assert r2.cached and "".join(replayed) == r1.text and len(calls) == 1
    # the measured JSON-mode call is cached apart from the streamed one
    llm.http = httpx.Client(transport=httpx.MockTransport(handler_factory(calls)),
                            base_url="https://x")
    assert not llm.chat(msgs, json_mode=True).cached and len(calls) == 2


def test_chat_stream_reports_the_daily_limit(tmp_path):
    calls = []
    llm = ChatClient("answer", transport=httpx.MockTransport(
        stream_handler(calls, 429, {"retry-after": "900"})), store_path=tmp_path / "llm.sqlite")
    with pytest.raises(QuotaExhausted, match="retry after 900s"):
        llm.chat_stream([{"role": "user", "content": "x"}], lambda _: None)
    assert len(calls) == 1


def test_a_call_larger_than_the_minute_window_is_let_through_when_it_is_empty():
    w = _Window(rpm=30, tpm=100)
    w.wait(500)  # used to sleep on an empty deque and raise IndexError
    assert [n for _, n in w.events] == [500]


def traced_runs(call) -> list[dict]:
    """Run `call` with tracing on against a mock LangSmith client: one merged dict per run."""
    ls = MagicMock(spec=Client)
    ls.tracing_sampling_rate = 1.0
    with tracing_context(enabled=True, client=ls):
        call()
    runs: dict = {}
    for c in ls.create_run.call_args_list:
        runs[str(c.kwargs["id"])] = dict(c.kwargs)
    for c in ls.update_run.call_args_list:
        runs[str(c.kwargs["run_id"])].update({k: v for k, v in c.kwargs.items()
                                              if v is not None})
    return list(runs.values())


def test_a_call_is_traced_with_model_and_tokens_and_a_cached_one_spends_none(tmp_path):
    llm = ChatClient("answer", transport=httpx.MockTransport(handler_factory([])),
                     store_path=tmp_path / "llm.sqlite")
    msgs = [{"role": "user", "content": "hello"}]
    llm.chat(msgs)
    (first,) = traced_runs(lambda: llm.chat([{"role": "user", "content": "new"}]))
    assert first["run_type"] == "llm" and first["inputs"]["messages"][0]["content"] == "new"
    assert "self" not in first["inputs"]
    meta = first["extra"]["metadata"]
    assert meta["ls_provider"] == "groq" and meta["ls_model_name"] == llm.model
    assert meta["cached"] is False and meta["role"] == "answer"
    assert meta["usage_metadata"] == {"input_tokens": 20, "output_tokens": 5, "total_tokens": 25}
    assert first["outputs"] == {"text": '{"answer": "ok"}'}

    (again,) = traced_runs(lambda: llm.chat(msgs))
    assert again["extra"]["metadata"]["cached"] is True
    assert "usage_metadata" not in again["extra"]["metadata"]


def test_a_stream_is_traced_without_its_callback(tmp_path):
    llm = ChatClient("answer", transport=httpx.MockTransport(stream_handler([])),
                     store_path=tmp_path / "llm.sqlite")
    (run,) = traced_runs(lambda: llm.chat_stream([{"role": "user", "content": "x"}],
                                                 lambda _: None))
    assert run["name"] == "chat_stream" and set(run["inputs"]) == {"messages", "json_mode"}
    assert run["extra"]["metadata"]["usage_metadata"]["total_tokens"] == 25


def test_tracing_off_records_nothing(tmp_path):
    ls = MagicMock(spec=Client)
    llm = ChatClient("answer", transport=httpx.MockTransport(handler_factory([])),
                     store_path=tmp_path / "llm.sqlite")
    with tracing_context(enabled=False, client=ls):
        assert llm.chat([{"role": "user", "content": "x"}]).text
        assert get_current_run_tree() is None
    ls.create_run.assert_not_called()


@pytest.mark.parametrize(("module", "expected"), [("evals.run", "False"),
                                                  ("statnav.api.app", "True")])
def test_evals_never_trace_and_the_api_still_can(module, expected):
    """In a new process, as importing `evals` changes the environment for good."""
    code = (f"import {module}; from statnav.config import base_config; base_config(); "
            "from langsmith.utils import tracing_is_enabled; print(tracing_is_enabled())")
    env = {**os.environ, "LANGSMITH_TRACING": "true"}
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, text=True,
                         capture_output=True, check=True)
    assert out.stdout.strip().splitlines()[-1] == expected
