import json

import pytest

from trace_waste.traceio import (
    TraceFormatError,
    estimate_tokens,
    parse_trace,
)


def line(obj) -> str:
    return json.dumps(obj)


def test_parse_reasoning_event():
    events = parse_trace(line({"type": "reasoning", "text": "thinking here"}))
    assert len(events) == 1
    event = events[0]
    assert event.type == "reasoning"
    assert event.text == "thinking here"
    assert event.index == 0


def test_tool_call_args_canonical_ignores_key_order():
    a = parse_trace(line({"type": "tool_call", "tool": "t", "args": {"x": 1, "y": 2}}))[0]
    b = parse_trace(line({"type": "tool_call", "tool": "t", "args": {"y": 2, "x": 1}}))[0]
    assert a.args_key == b.args_key
    assert a.tool == "t"


def test_tool_result_text_from_result_field():
    event = parse_trace(
        line({"type": "tool_result", "call_id": "c1", "result": "the answer"})
    )[0]
    assert event.text == "the answer"
    assert event.call_id == "c1"


def test_tool_result_text_from_output_field_and_non_string():
    event = parse_trace(
        line({"type": "tool_result", "output": {"temp": 58}})
    )[0]
    assert "58" in event.text


def test_context_event():
    event = parse_trace(
        line({"type": "context", "id": "ctx-1", "text": "some context"})
    )[0]
    assert event.type == "context"
    assert event.id == "ctx-1"
    assert event.text == "some context"


def test_unknown_type_kept_as_other():
    event = parse_trace(line({"type": "system_note", "text": "hi"}))[0]
    assert event.type == "other"
    assert event.tokens > 0


def test_blank_lines_skipped():
    text = "\n" + line({"type": "reasoning", "text": "a"}) + "\n\n  \n"
    events = parse_trace(text)
    assert len(events) == 1


def test_malformed_line_raises_with_line_number():
    text = line({"type": "reasoning", "text": "ok"}) + "\n{not json"
    with pytest.raises(TraceFormatError) as excinfo:
        parse_trace(text)
    assert "line 2" in str(excinfo.value)


def test_non_object_line_raises():
    with pytest.raises(TraceFormatError):
        parse_trace("[1, 2, 3]")


def test_explicit_tokens_field_used():
    event = parse_trace(
        line({"type": "reasoning", "text": "short", "tokens": 1234})
    )[0]
    assert event.tokens == 1234


def test_token_estimate_is_chars_over_four():
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("abcde") == 2
    assert estimate_tokens("a" * 40) == 10


def test_refs_parsed():
    event = parse_trace(
        line({"type": "text", "text": "answer", "refs": ["call-1", "ctx-9"]})
    )[0]
    assert event.refs == ("call-1", "ctx-9")
