import json

import httpx
import pytest

from statnav.llm.client import ChatClient, QuotaExhausted


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
