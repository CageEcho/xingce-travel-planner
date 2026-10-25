"""LLM 提供方切换：DeepSeek 路径用「强制工具调用 + Pydantic 校验」拿结构化结果。离线，全部 mock。"""
from types import SimpleNamespace

import pytest

from app.core import llm
from app.core.config import settings
from app.core.errors import AppError
from app.schemas.slots import SlotExtraction


class FakeStream:
    """模拟 client.messages.stream：可携带原始 partial_json 增量。"""
    def __init__(self, response, raw_json=""):
        self.response, self.raw_json = response, raw_json

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        if self.raw_json:
            yield SimpleNamespace(type="content_block_delta", delta=SimpleNamespace(type="input_json_delta", partial_json=self.raw_json))

    def get_final_message(self):
        return self.response


class FakeMessages:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def stream(self, **kwargs):
        self.calls.append(kwargs)
        item = self.responses.pop(0)
        return item if isinstance(item, FakeStream) else FakeStream(item)


def tool_use(inp):
    return SimpleNamespace(type="tool_use", name=llm.RESULT_TOOL, input=inp)


def resp(*blocks, stop="tool_use"):
    return SimpleNamespace(content=list(blocks), stop_reason=stop, usage=SimpleNamespace(input_tokens=100, output_tokens=20, cache_read_input_tokens=0))


GOOD = {"slots": {"adults": {"value": 2, "source": "client_verbatim", "confidence": 0.9}}, "followups": [], "notes": ""}


@pytest.fixture
def deepseek(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "deepseek")
    monkeypatch.setattr(settings, "deepseek_model", "deepseek-v4-pro")

    def use(responses):
        fake = FakeMessages(responses)
        monkeypatch.setattr(llm, "get_client", lambda: SimpleNamespace(messages=fake))
        return fake
    return use


def test_deepseek_forces_result_tool_with_pydantic_schema(deepseek):
    fake = deepseek([resp(tool_use(GOOD))])
    res = llm.parse_structured(system="S", user="U", output_format=SlotExtraction, max_tokens=800, effort="high")
    assert isinstance(res.parsed, SlotExtraction)
    assert res.parsed.slots.adults.value == 2
    assert res.retried is False
    call = fake.calls[0]
    assert call["model"] == "deepseek-v4-pro"
    assert call["tools"][0]["input_schema"] == SlotExtraction.model_json_schema()
    assert call["output_config"] == {"effort": "high"}
    assert "output_format" not in call          # 该端点不支持 Claude 的结构化输出参数
    assert isinstance(call["system"], str)      # cache_control 被忽略，直接传字符串


def test_deepseek_schema_violation_retries_with_error_feedback(deepseek, monkeypatch):
    monkeypatch.setattr(settings, "deepseek_max_attempts", 3)
    bad = {"slots": {"adults": {"value": 2, "source": "guess", "confidence": 5}}, "followups": []}
    fake = deepseek([resp(tool_use(bad)), resp(tool_use(GOOD))])
    res = llm.parse_structured(system="S", user="U", output_format=SlotExtraction, max_tokens=800)
    assert res.retried is True
    second_user = fake.calls[1]["messages"][0]["content"]
    assert "<format_errors>" in second_user and "source" in second_user


def test_deepseek_no_tool_call_twice_is_invalid_output(deepseek, monkeypatch):
    monkeypatch.setattr(settings, "deepseek_max_attempts", 2)
    deepseek([resp(SimpleNamespace(type="text", text="好的"), stop="end_turn"), resp(SimpleNamespace(type="text", text="..."), stop="end_turn")])
    with pytest.raises(AppError) as ei:
        llm.parse_structured(system="S", user="U", output_format=SlotExtraction, max_tokens=800)
    assert ei.value.code == "LLM_INVALID_OUTPUT"


def test_deepseek_default_disables_thinking_and_forces_tool(deepseek, monkeypatch):
    monkeypatch.setattr(settings, "deepseek_thinking", False)
    fake = deepseek([resp(tool_use(GOOD))])
    llm.parse_structured(system="S", user="U", output_format=SlotExtraction, max_tokens=800)
    assert fake.calls[0]["thinking"] == {"type": "disabled"}
    assert fake.calls[0]["tool_choice"] == {"type": "tool", "name": llm.RESULT_TOOL}


def test_deepseek_thinking_mode_uses_auto_tool_choice(deepseek, monkeypatch):
    # 思考模式与强制 tool_choice 互斥（DeepSeek 400），改为 auto + 指令
    monkeypatch.setattr(settings, "deepseek_thinking", True)
    fake = deepseek([resp(tool_use(GOOD))])
    llm.parse_structured(system="S", user="U", output_format=SlotExtraction, max_tokens=800)
    assert "thinking" not in fake.calls[0]
    assert fake.calls[0]["tool_choice"] == {"type": "auto"}
    assert llm.RESULT_TOOL in fake.calls[0]["system"]


def test_active_model_follows_provider(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "anthropic")
    assert llm.active_model() == settings.claude_model
    monkeypatch.setattr(settings, "llm_provider", "deepseek")
    assert llm.active_model() == settings.deepseek_model


def test_deepseek_client_requires_key(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "deepseek")
    monkeypatch.setattr(settings, "deepseek_api_key", "")
    llm.reset_client()
    with pytest.raises(AppError) as ei:
        llm.get_client()
    assert ei.value.code == "LLM_FAILED"
    llm.reset_client()


def test_deepseek_client_uses_compat_base_url(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "deepseek")
    monkeypatch.setattr(settings, "deepseek_api_key", "sk-test")
    llm.reset_client()
    client = llm.get_client()
    assert "api.deepseek.com/anthropic" in str(client.base_url)
    llm.reset_client()


def test_model_ssl_context_merges_configured_bundle_and_proxy_ca(monkeypatch, tmp_path):
    primary = tmp_path / "system-ca.pem"
    proxy = tmp_path / "proxy-ca.pem"
    primary.write_text("system", encoding="utf-8")
    proxy.write_text("proxy", encoding="utf-8")
    loaded: list[str] = []
    fake_context = SimpleNamespace(load_verify_locations=lambda *, cafile: loaded.append(cafile))
    monkeypatch.setattr(settings, "llm_ca_bundle", str(primary))
    monkeypatch.setenv("SSL_CERT_FILE", str(proxy))
    monkeypatch.setattr(llm.ssl, "create_default_context", lambda *, cafile: fake_context)

    assert llm._model_ssl_context() is fake_context
    assert loaded == [str(proxy)]


def test_model_ssl_context_rejects_missing_configured_bundle(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "llm_ca_bundle", str(tmp_path / "missing.pem"))
    with pytest.raises(AppError) as exc:
        llm._model_ssl_context()
    assert exc.value.code == "LLM_FAILED"


def test_unwrap_tool_input_handles_result_wrapper():
    inner = {"slots": {}, "followups": [], "notes": ""}
    assert llm.unwrap_tool_input({"result": inner}, SlotExtraction) == inner
    assert llm.unwrap_tool_input({"output": {"result": inner}}, SlotExtraction) == inner
    assert llm.unwrap_tool_input(inner, SlotExtraction) == inner          # 已是正确形状不动
    assert llm.unwrap_tool_input({"a": inner, "b": inner}, SlotExtraction) == {"a": inner, "b": inner}   # 歧义不解包


def test_deepseek_empty_tool_input_recovered_from_raw_stream_json(deepseek):
    import json
    raw = json.dumps(GOOD, ensure_ascii=False)[:-1] + ",}"      # 带尾逗号的瑕疵 JSON：端点会丢成 {}
    deepseek([FakeStream(resp(tool_use({})), raw_json=raw)])
    res = llm.parse_structured(system="S", user="U", output_format=SlotExtraction, max_tokens=800)
    assert res.parsed.slots.adults.value == 2 and res.retried is False


def test_loads_lenient_repairs_truncation_and_trailing_commas():
    assert llm._loads_lenient('{"a": [1, 2,], "b": {"c": 1,},}') == {"a": [1, 2], "b": {"c": 1}}
    assert llm._loads_lenient('{"days": [{"x": 1}, {"y": "abc') == {"days": [{"x": 1}, {"y": "abc"}]}
    assert llm._loads_lenient("not json") is None


class MalformedStream(FakeStream):
    """模拟 SDK 流式累积器在 content_block_stop 时解析工具参数失败（真实跑测遇到的尾逗号）。"""
    def __iter__(self):
        yield SimpleNamespace(type="content_block_delta", delta=SimpleNamespace(type="input_json_delta", partial_json=self.raw_json))
        raise ValueError("Unable to parse tool parameter JSON from model. Error: trailing comma")


def test_deepseek_recovers_trailing_comma_tool_json(deepseek):
    raw = '{"slots": {"adults": {"value": 2, "source": "client_verbatim", "confidence": 0.9},}, "followups": [], "notes": ""}'
    fake = deepseek([MalformedStream(None, raw)])
    res = llm.parse_structured(system="s", user="u", output_format=SlotExtraction, max_tokens=500)
    assert res.parsed.slots.adults.value == 2 and res.retried
    assert len(fake.calls) == 1                     # 宽容解析直接救回，不重复请求


def test_deepseek_unrecoverable_tool_json_retries_with_feedback(deepseek, monkeypatch):
    monkeypatch.setattr(settings, "deepseek_max_attempts", 2)
    fake = deepseek([MalformedStream(None, '{"slots": {"adults": '), resp(tool_use(GOOD))])
    res = llm.parse_structured(system="s", user="u", output_format=SlotExtraction, max_tokens=500)
    assert res.parsed.slots.adults.value == 2
    assert "不是合法 JSON" in fake.calls[1]["messages"][0]["content"]


class DroppedStream(FakeStream):
    """模拟流式传输中途断开（真实跑测遇到的 httpx.RemoteProtocolError）。"""
    def __iter__(self):
        import httpx
        raise httpx.RemoteProtocolError("peer closed connection without sending complete message body")
        yield  # pragma: no cover


def test_deepseek_transport_error_retries_then_succeeds(deepseek, monkeypatch):
    monkeypatch.setattr(settings, "deepseek_max_attempts", 2)
    deepseek([DroppedStream(None), resp(tool_use(GOOD))])
    assert llm.parse_structured(system="s", user="u", output_format=SlotExtraction, max_tokens=500).parsed.slots.adults.value == 2


def test_deepseek_transport_error_exhausted_is_llm_failed(deepseek, monkeypatch):
    monkeypatch.setattr(settings, "deepseek_max_attempts", 2)
    deepseek([DroppedStream(None), DroppedStream(None)])
    with pytest.raises(AppError) as e:
        llm.parse_structured(system="s", user="u", output_format=SlotExtraction, max_tokens=500)
    assert e.value.code == "LLM_FAILED"          # LLM_FAILED 才会触发规则编排降级
