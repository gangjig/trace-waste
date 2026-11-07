import io
import json
import sys

from trace_waste.cli import main
from trace_waste.sample import SAMPLE_TRACE

_DUP = "the agent keeps repeating the same reasoning step over and over"
WASTEFUL = "\n".join(
    [
        json.dumps({"type": "reasoning", "text": _DUP}),
        json.dumps({"type": "reasoning", "text": _DUP}),
    ]
)


def write(tmp_path, text, name="trace.jsonl"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_analyze_text_report(tmp_path, capsys):
    path = write(tmp_path, SAMPLE_TRACE)
    assert main(["analyze", path]) == 0
    out = capsys.readouterr().out
    assert "trace-waste report" in out
    assert "repeated-tool-call" in out
    assert "total waste:" in out


def test_analyze_json_output(tmp_path, capsys):
    path = write(tmp_path, SAMPLE_TRACE)
    assert main(["analyze", path, "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["total_tokens"] > 0
    assert data["waste_tokens"] > 0
    assert "repeated-tool-call" in data["categories"]


def test_analyze_clean_trace_exit_zero(tmp_path, capsys):
    path = write(
        tmp_path,
        json.dumps({"type": "reasoning", "text": "one short unique step"}),
    )
    assert main(["analyze", path]) == 0
    assert "no waste detected" in capsys.readouterr().out


def test_fail_above_triggers_exit_one(tmp_path):
    path = write(tmp_path, WASTEFUL)
    assert main(["analyze", path, "--fail-above", "10"]) == 1


def test_fail_above_below_threshold_exit_zero(tmp_path):
    path = write(tmp_path, WASTEFUL)
    assert main(["analyze", path, "--fail-above", "99"]) == 0


def test_missing_file_exit_two(tmp_path, capsys):
    assert main(["analyze", str(tmp_path / "nope.jsonl")]) == 2
    assert "cannot read" in capsys.readouterr().err


def test_malformed_trace_exit_two(tmp_path, capsys):
    path = write(tmp_path, "{not json")
    assert main(["analyze", path]) == 2
    assert "line 1" in capsys.readouterr().err


def test_demo_runs(capsys):
    assert main(["demo"]) == 0
    out = capsys.readouterr().out
    assert "unused-context" in out
    assert "total waste:" in out


def test_stdin_input(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO(SAMPLE_TRACE))
    assert main(["analyze", "-"]) == 0
    assert "trace-waste report" in capsys.readouterr().out


def test_judge_command_replaces_heuristics(tmp_path, capsys):
    script = tmp_path / "judge.py"
    script.write_text(
        "import json, sys\n"
        "events = json.load(sys.stdin)\n"
        "print(json.dumps([{'index': 0, 'category': 'custom-check',"
        " 'reason': 'flagged by the test judge'}]))\n",
        encoding="utf-8",
    )
    path = write(
        tmp_path,
        json.dumps({"type": "reasoning", "text": "a perfectly fine step"}),
    )
    rc = main(
        [
            "analyze",
            path,
            "--json",
            "--judge-command",
            f"{sys.executable} {script}",
        ]
    )
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert set(data["categories"]) == {"custom-check"}
    assert data["findings"][0]["reason"] == "flagged by the test judge"


def test_judge_command_failure_exit_two(tmp_path, capsys):
    path = write(
        tmp_path,
        json.dumps({"type": "reasoning", "text": "a perfectly fine step"}),
    )
    rc = main(["analyze", path, "--judge-command", "false"])
    assert rc == 2
    assert "judge command" in capsys.readouterr().err
