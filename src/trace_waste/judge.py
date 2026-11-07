"""Judges: the components that label the wasteful parts of a trace.

A judge takes the parsed events and returns findings. Each finding names
one primary event, a waste category, a human-readable reason, and the
token spans it claims (a span is a slice of one event's tokens; the
report layer guarantees spans never double-count the same tokens).

Two judges ship with trace-waste:

- ``HeuristicJudge`` -- the default. Deterministic, offline, no API key:
  four documented heuristics, one per waste category.
- ``CommandJudge`` -- optional and off by default. Runs an external
  command (for example an LLM-backed script you control): the events go
  to the command's stdin as a JSON array, and the command must print a
  JSON array of findings, each ``{"index": int, "category": str,
  "reason": str}``. When a command judge is configured it *replaces* the
  heuristics rather than merging with them.

Reference rule (used by the ``unused-*`` heuristics): a tool result or a
context segment counts as *referenced* by a later step when that step
lists its id in ``refs``, mentions its id in its text, or quotes its text
(the full text, or its first 30 normalized characters when longer).
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field

from .traceio import Event, canonical_json

CATEGORIES = (
    "repeated-tool-call",
    "redundant-reasoning",
    "unused-tool-result",
    "unused-context",
)

_QUOTE_PREFIX = 30
_MIN_REASONING_WORDS = 4
_WORD_RE = re.compile(r"\w+")


class JudgeError(RuntimeError):
    """Raised when an external judge command fails or misbehaves."""


@dataclass(frozen=True)
class Span:
    """A claim on ``tokens`` tokens of the event at ``index``."""

    index: int
    tokens: int


@dataclass
class Finding:
    """One labeled wasteful part of a trace."""

    category: str
    index: int
    reason: str
    spans: tuple = ()
    tokens: int = field(default=0, compare=False)  # filled by report.analyze


class Judge:
    """Interface for waste judges."""

    def judge(self, events: list[Event]) -> list[Finding]:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _normalize(text: str) -> str:
    return " ".join(text.split())


def _quotes(later_text: str, target_text: str) -> bool:
    """True when later_text quotes target_text (see module docstring)."""
    target = _normalize(target_text)
    if not target:
        return False
    later = _normalize(later_text)
    if target in later:
        return True
    return len(target) >= _QUOTE_PREFIX and target[:_QUOTE_PREFIX] in later


def is_referenced(events: list[Event], target: Event) -> bool:
    """True when any later event references the target event."""
    keys = {k for k in (target.id, target.call_id) if k}
    for later in events:
        if later.index <= target.index:
            continue
        if keys and keys.intersection(later.refs):
            return True
        if later.text:
            if any(len(k) >= 3 and k in later.text for k in keys):
                return True
            if _quotes(later.text, target.text):
                return True
    return False


def pair_results(events: list[Event]) -> dict:
    """Map each tool_call event index to its tool_result event.

    A result pairs with the call whose id matches its ``call_id``; failing
    that, with the earliest earlier call that has no result yet.
    """
    calls = [e for e in events if e.type == "tool_call"]
    by_id = {e.id: e for e in calls if e.id}
    taken: set = set()
    pairs: dict = {}
    for result in (e for e in events if e.type == "tool_result"):
        call = None
        named = by_id.get(result.call_id) if result.call_id else None
        if named is not None and named.index not in taken:
            call = named
        else:
            for candidate in calls:
                if candidate.index < result.index and candidate.index not in taken:
                    call = candidate
                    break
        if call is not None:
            pairs[call.index] = result
            taken.add(call.index)
    return pairs


def _word_set(text: str) -> frozenset:
    return frozenset(_WORD_RE.findall(text.lower()))


def jaccard(a: frozenset, b: frozenset) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# ---------------------------------------------------------------------------
# The default heuristic judge
# ---------------------------------------------------------------------------


class HeuristicJudge(Judge):
    """Deterministic offline judge implementing all four categories."""

    def __init__(self, similarity: float = 0.8):
        if not 0 < similarity <= 1:
            raise ValueError("similarity must be in (0, 1]")
        self.similarity = similarity

    def judge(self, events: list[Event]) -> list[Finding]:
        findings: list[Finding] = []
        findings.extend(self._repeated_tool_calls(events))
        findings.extend(self._redundant_reasoning(events))
        findings.extend(self._unused(events, "tool_result", "unused-tool-result"))
        findings.extend(self._unused(events, "context", "unused-context"))
        return findings

    def _repeated_tool_calls(self, events: list[Event]) -> list[Finding]:
        pairs = pair_results(events)
        groups: dict = {}
        for call in (e for e in events if e.type == "tool_call"):
            groups.setdefault((call.tool, call.args_key), []).append(call)
        findings = []
        for (tool, _key), group in groups.items():
            if len(group) < 2:
                continue
            first = group[0]
            first_result = pairs.get(first.index)
            for call in group[1:]:
                result = pairs.get(call.index)
                if (
                    first_result is not None
                    and result is not None
                    and first_result.text != result.text
                ):
                    continue  # same question, different answer: a re-check
                spans = [Span(call.index, call.tokens)]
                if result is not None:
                    spans.append(Span(result.index, result.tokens))
                findings.append(
                    Finding(
                        category="repeated-tool-call",
                        index=call.index,
                        reason=(
                            f"same call as event {first.index} "
                            f"(tool {tool!r}, identical arguments and result)"
                        ),
                        spans=tuple(spans),
                    )
                )
        return findings

    def _redundant_reasoning(self, events: list[Event]) -> list[Finding]:
        blocks = []
        for event in events:
            if event.type in ("reasoning", "text"):
                words = _word_set(event.text)
                if len(words) >= _MIN_REASONING_WORDS:
                    blocks.append((event, words))
        findings = []
        for pos, (event, words) in enumerate(blocks):
            for earlier, earlier_words in blocks[:pos]:
                similarity = jaccard(words, earlier_words)
                if similarity >= self.similarity:
                    findings.append(
                        Finding(
                            category="redundant-reasoning",
                            index=event.index,
                            reason=(
                                f"near-duplicate of event {earlier.index} "
                                f"(word overlap {similarity:.2f})"
                            ),
                            spans=(Span(event.index, event.tokens),),
                        )
                    )
                    break
        return findings

    def _unused(self, events: list[Event], etype: str, category: str) -> list[Finding]:
        findings = []
        for event in events:
            if event.type != etype:
                continue
            if not is_referenced(events, event):
                findings.append(
                    Finding(
                        category=category,
                        index=event.index,
                        reason="never referenced by any later step",
                        spans=(Span(event.index, event.tokens),),
                    )
                )
        return findings


# ---------------------------------------------------------------------------
# The optional external-command judge
# ---------------------------------------------------------------------------


def event_to_dict(event: Event) -> dict:
    """The JSON view of an event handed to judge commands."""
    return {
        "index": event.index,
        "type": event.type,
        "id": event.id,
        "text": event.text,
        "tool": event.tool,
        "args": event.args,
        "call_id": event.call_id,
        "refs": list(event.refs),
        "tokens": event.tokens,
    }


class CommandJudge(Judge):
    """Judge backed by an external command (opt-in, off by default).

    The command receives the events as a JSON array on stdin and must
    print a JSON array of findings:
    ``[{"index": 3, "category": "...", "reason": "..."}]``.
    """

    def __init__(self, command: str, timeout: float = 120.0):
        self.command = command
        self.timeout = timeout

    def judge(self, events: list[Event]) -> list[Finding]:
        payload = json.dumps([event_to_dict(e) for e in events])
        try:
            proc = subprocess.run(
                self.command,
                shell=True,
                input=payload,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise JudgeError(f"judge command failed to run: {exc}") from exc
        if proc.returncode != 0:
            detail = proc.stderr.strip()[:200] if proc.stderr else "no stderr"
            raise JudgeError(
                f"judge command exited with {proc.returncode}: {detail}"
            )
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise JudgeError(f"judge command did not print JSON: {exc}") from exc
        if not isinstance(data, list):
            raise JudgeError("judge command must print a JSON array of findings")
        findings = []
        for item in data:
            if not isinstance(item, dict) or not isinstance(item.get("index"), int):
                raise JudgeError(f"invalid finding from judge command: {item!r}")
            index = item["index"]
            if not 0 <= index < len(events):
                raise JudgeError(f"judge finding index out of range: {index}")
            findings.append(
                Finding(
                    category=str(item.get("category") or "custom"),
                    index=index,
                    reason=str(item.get("reason") or ""),
                    spans=(Span(index, events[index].tokens),),
                )
            )
        return findings


def get_judge(judge_command: str | None = None, similarity: float = 0.8) -> Judge:
    """Build the configured judge: command judge if given, else heuristics."""
    if judge_command:
        return CommandJudge(judge_command)
    return HeuristicJudge(similarity=similarity)


# Kept for callers that prefer the raw canonical rendering.
__all__ = [
    "CATEGORIES",
    "CommandJudge",
    "Finding",
    "HeuristicJudge",
    "Judge",
    "JudgeError",
    "Span",
    "canonical_json",
    "event_to_dict",
    "get_judge",
    "is_referenced",
    "jaccard",
    "pair_results",
]
