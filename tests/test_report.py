import json

from trace_waste.judge import HeuristicJudge
from trace_waste.report import analyze, render_json, render_text
from trace_waste.sample import SAMPLE_TRACE
from trace_waste.traceio import parse_trace


def trace(*objs):
    return parse_trace("\n".join(json.dumps(o) for o in objs))


def test_total_tokens_is_sum_of_events():
    events = trace(
        {"type": "reasoning", "text": "a" * 40, "tokens": 10},
        {"type": "reasoning", "text": "b" * 80, "tokens": 20},
    )
    report = analyze(events, HeuristicJudge())
    assert report.events == 2
    assert report.total_tokens == 30


def test_waste_percent_math():
    events = parse_trace(SAMPLE_TRACE)
    report = analyze(events, HeuristicJudge())
    expected = 100.0 * report.waste_tokens / report.total_tokens
    assert report.waste_percent == expected
    assert 0 < report.waste_percent < 100


def test_per_category_aggregation_covers_all_four():
    report = analyze(parse_trace(SAMPLE_TRACE), HeuristicJudge())
    assert set(report.categories) == {
        "repeated-tool-call",
        "redundant-reasoning",
        "unused-tool-result",
        "unused-context",
    }
    assert sum(t.waste_tokens for t in report.categories.values()) == (
        report.waste_tokens
    )


def test_no_double_counting_across_categories():
    # The repeated call's result is *also* never referenced later, so two
    # categories point at it; its tokens may only be counted once.
    events = trace(
        {"type": "tool_call", "id": "c1", "tool": "t", "args": {"x": 1}},
        {"type": "tool_result", "call_id": "c1", "result": "r" * 40},
        {"type": "tool_call", "id": "c2", "tool": "t", "args": {"x": 1}},
        {"type": "tool_result", "call_id": "c2", "result": "r" * 40},
    )
    report = analyze(events, HeuristicJudge())
    repeated = report.categories["repeated-tool-call"]
    # waste = second call + its result, exactly once
    assert repeated.waste_tokens == events[2].tokens + events[3].tokens
    assert report.waste_tokens == repeated.waste_tokens


def test_savings_usd_conversion():
    report = analyze(parse_trace(SAMPLE_TRACE), HeuristicJudge())
    usd = report.savings_usd(3.00)
    assert usd is not None
    assert abs(usd - report.waste_tokens * 3.00 / 1_000_000) < 1e-12
    assert report.savings_usd(None) is None


def test_empty_trace_report():
    report = analyze([], HeuristicJudge())
    assert report.total_tokens == 0
    assert report.waste_tokens == 0
    assert report.waste_percent == 0.0
    assert "no waste detected" in render_text(report)


def test_json_render_structure():
    report = analyze(parse_trace(SAMPLE_TRACE), HeuristicJudge())
    data = render_json(report, price_per_1m=3.00)
    assert data["events"] == report.events
    assert data["total_tokens"] == report.total_tokens
    assert data["waste_tokens"] == report.waste_tokens
    assert data["savings"]["tokens"] == report.waste_tokens
    assert data["savings"]["usd"] is not None
    assert {f["category"] for f in data["findings"]} == set(report.categories)
    indexes = [f["index"] for f in data["findings"]]
    assert indexes == sorted(indexes)
