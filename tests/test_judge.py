import json

from trace_waste.judge import HeuristicJudge
from trace_waste.traceio import parse_trace


def trace(*objs):
    return parse_trace("\n".join(json.dumps(o) for o in objs))


def categories(findings):
    return [f.category for f in findings]


REASONING = (
    "The user wants the weather in Arlington today. I should call the "
    "weather tool for Arlington and then summarize the result briefly."
)


def call(call_id, tool="get_weather", args=None):
    return {
        "type": "tool_call",
        "id": call_id,
        "tool": tool,
        "args": args if args is not None else {"city": "Arlington, VA"},
    }


def result(call_id, text="Sunny, high 58F, no rain expected today."):
    return {"type": "tool_result", "call_id": call_id, "result": text}


# -- repeated-tool-call -----------------------------------------------------


def test_repeated_tool_call_flagged():
    events = trace(call("c1"), result("c1"), call("c2"), result("c2"))
    findings = HeuristicJudge().judge(events)
    repeats = [f for f in findings if f.category == "repeated-tool-call"]
    assert len(repeats) == 1
    finding = repeats[0]
    assert finding.index == 2
    span_tokens = sum(s.tokens for s in finding.spans)
    assert span_tokens == events[2].tokens + events[3].tokens


def test_repeated_call_with_different_result_not_flagged():
    events = trace(
        call("c1"),
        result("c1", "Sunny and warm all day."),
        call("c2"),
        result("c2", "Rain starting at noon."),
    )
    findings = HeuristicJudge().judge(events)
    assert "repeated-tool-call" not in categories(findings)


def test_three_identical_calls_give_two_findings():
    events = trace(
        call("c1"), result("c1"), call("c2"), result("c2"),
        call("c3"), result("c3"),
        {"type": "text", "text": "Sunny, high 58F, no rain expected today.",
         "refs": ["c1"]},
    )
    findings = HeuristicJudge().judge(events)
    repeats = [f for f in findings if f.category == "repeated-tool-call"]
    assert len(repeats) == 2


def test_different_arguments_not_flagged():
    events = trace(
        call("c1", args={"city": "Arlington, VA"}),
        result("c1"),
        call("c2", args={"city": "Boston, MA"}),
        result("c2"),
    )
    findings = HeuristicJudge().judge(events)
    assert "repeated-tool-call" not in categories(findings)


def test_repeated_call_without_any_results_flagged():
    events = trace(call("c1"), call("c2"))
    findings = HeuristicJudge().judge(events)
    assert categories(findings) == ["repeated-tool-call"]


# -- redundant-reasoning ----------------------------------------------------


def test_exact_duplicate_reasoning_flagged():
    events = trace(
        {"type": "reasoning", "text": REASONING},
        {"type": "reasoning", "text": REASONING},
    )
    findings = HeuristicJudge().judge(events)
    assert categories(findings) == ["redundant-reasoning"]
    assert findings[0].index == 1


def test_near_duplicate_reasoning_flagged():
    a = ("the agent should check the weather forecast before planning "
         "the outdoor event schedule today")
    b = ("the agent should check the weather forecast before planning "
         "the outdoor event schedule tomorrow")
    events = trace(
        {"type": "reasoning", "text": a},
        {"type": "reasoning", "text": b},
    )
    findings = HeuristicJudge().judge(events)
    assert categories(findings) == ["redundant-reasoning"]


def test_dissimilar_reasoning_not_flagged():
    events = trace(
        {"type": "reasoning", "text": REASONING},
        {"type": "reasoning",
         "text": "Now I need to book a flight and compare hotel prices "
                 "for the conference trip next month instead."},
    )
    findings = HeuristicJudge().judge(events)
    assert findings == []


def test_similarity_threshold_respected():
    a = ("the agent should check the weather forecast before planning "
         "the outdoor event schedule today")
    b = ("the agent should check the weather forecast before planning "
         "the outdoor event schedule tomorrow")
    events = trace(
        {"type": "reasoning", "text": a},
        {"type": "reasoning", "text": b},
    )
    findings = HeuristicJudge(similarity=0.95).judge(events)
    assert findings == []


# -- unused-tool-result -----------------------------------------------------


def test_unused_tool_result_flagged():
    events = trace(
        call("c1", tool="get_news", args={"topic": "sports"}),
        result("c1", "Local football scores from Friday night games."),
        {"type": "text", "text": "Here is your weather summary instead."},
    )
    findings = HeuristicJudge().judge(events)
    assert categories(findings) == ["unused-tool-result"]
    assert findings[0].index == 1


def test_result_referenced_by_refs_not_flagged():
    events = trace(
        call("c1"),
        result("c1"),
        {"type": "text", "text": "Summary based on the call.",
         "refs": ["c1"]},
    )
    findings = HeuristicJudge().judge(events)
    assert findings == []


def test_result_quoted_later_not_flagged():
    events = trace(
        call("c1"),
        result("c1", "Sunny, high 58F, no rain expected today."),
        {"type": "text",
         "text": "Forecast: Sunny, high 58F, no rain expected today."},
    )
    findings = HeuristicJudge().judge(events)
    assert findings == []


# -- unused-context ---------------------------------------------------------


def test_unused_context_flagged():
    events = trace(
        {"type": "context", "id": "ctx-old",
         "text": "Legacy formatting rules from an old handbook."},
        {"type": "reasoning", "text": REASONING},
    )
    findings = HeuristicJudge().judge(events)
    assert categories(findings) == ["unused-context"]
    assert findings[0].index == 0


def test_context_referenced_by_id_mention_not_flagged():
    events = trace(
        {"type": "context", "id": "ctx-rules",
         "text": "Always answer in English and be concise."},
        {"type": "reasoning",
         "text": "Following ctx-rules, I will keep this answer short "
                 "and in English for the user today."},
    )
    findings = HeuristicJudge().judge(events)
    assert findings == []


def test_empty_trace_no_findings():
    assert HeuristicJudge().judge([]) == []
