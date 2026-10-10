import json

import httpx
import pytest

from statnav.llm.client import ChatClient, QuotaExhausted, _Window


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
