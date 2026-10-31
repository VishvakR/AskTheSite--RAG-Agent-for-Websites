"""Provider-neutral chat layer: thinking split, prompt fallback, wire formats."""

from app.llm import ChatMessage, LLMManager, ToolCall
from app.llm.main import chat, chat_via_prompt
from app.llm.thinking import ThinkTagParser, split_thinking
from app.llm.types import Stop, TextDelta, ThinkingDelta


def _run(parser: ThinkTagParser, chunks):
    out = []
    for c in chunks:
        out += parser.feed(c)
    out += parser.flush()
    merged = {}
    for kind, text in out:
        merged[kind] = merged.get(kind, "") + text
    return merged


def test_think_tags_split_across_chunks():
    got = _run(ThinkTagParser(), ["Hi <thi", "nk>plan", " it</th", "ink>\n\nAnswer [1]."])
    assert got == {"text": "Hi Answer [1].", "thinking": "plan it"}


def test_text_that_only_looks_like_a_tag_is_kept():
    assert split_thinking("a < b and <b>bold</b>") == ("a < b and <b>bold</b>", "")


def test_thinking_variant_tag():
    assert split_thinking("<thinking>x</thinking>y") == ("y", "x")


class _PromptOnly:
    """A provider with only the old prompt API, like the test FakeLLM."""

    model_name = "p"

    def stream_response(self, prompt):
        yield from ["<think>hmm</think>", "Done [1]."]


def test_prompt_only_provider_gets_a_thinking_channel():
    events = list(chat(_PromptOnly(), [ChatMessage.system("s"), ChatMessage.user("q")]))
    assert [e.text for e in events if isinstance(e, ThinkingDelta)] == ["hmm"]
    assert "".join(e.text for e in events if isinstance(e, TextDelta)) == "Done [1]."
    stop = events[-1]
    assert isinstance(stop, Stop) and stop.message.thinking == "hmm"


def test_anthropic_wire_format_groups_parallel_tool_results():
    from app.llm.providers.anthropic import AnthropicModel

    a, b = ToolCall("t1", "search_site", {"query": "x"}), ToolCall("t2", "read_page", {"url": "u"})
    system, msgs = AnthropicModel._to_api([
        ChatMessage.system("rules"),
        ChatMessage.user("q"),
        ChatMessage(role="assistant", content="", tool_calls=[a, b]),
        ChatMessage.tool_result(a, "r1"),
        ChatMessage.tool_result(b, "boom", is_error=True),
    ])
    assert system == "rules"
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    results = msgs[2]["content"]
    assert [r["tool_use_id"] for r in results] == ["t1", "t2"]
    assert results[1]["is_error"] is True


def test_anthropic_replays_raw_blocks_unchanged():
    from app.llm.providers.anthropic import AnthropicModel

    raw = [{"type": "thinking", "thinking": "…", "signature": "sig"}, {"type": "text", "text": "hi"}]
    _, msgs = AnthropicModel._to_api([
        ChatMessage.user("q"),
        ChatMessage(role="assistant", content="hi", raw=raw, raw_provider="anthropic"),
    ])
    assert msgs[1]["content"] is raw


def test_availability_lists_every_registered_provider():
    rows = {p["provider"]: p for p in LLMManager.availability()}
    assert {"opensource", "anthropic", "openai", "openai_compatible", "fake"} <= set(rows)
    for row in rows.values():
        assert row["available"] or row["reason"]
    claude = {s["id"]: s for s in rows["anthropic"]["specs"]}
    assert claude["claude-opus-5-5"]["supports_tools"]


def test_unknown_model_gets_provider_defaults():
    spec = LLMManager.spec("openai", "some-new-model")
    assert spec.supports_tools and spec.id == "some-new-model"
