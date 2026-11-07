"""Trace model and JSONL parsing for trace-waste.

A trace is a JSONL file: one JSON object per line, one object per event in
an agent run. Parsing is deliberately tolerant:

- Unknown event types are kept (they count toward the token total, and an
  explicit ``tokens`` field on them is honored) but are not waste-checked.
- Blank lines are skipped.
- Most fields are optional; missing text counts as empty.
- An event may carry an integer ``tokens`` field with its true token
  count. When it does not, the count is estimated as characters / 4.

Recognized event types and the fields each one reads:

- ``reasoning`` / ``text``: ``text`` (or ``content``), optional ``id``,
  optional ``refs``.
- ``tool_call``: ``tool`` (or ``name``), ``args`` (or ``arguments``),
  ``id`` (or ``call_id``).
- ``tool_result``: ``result`` (or ``content`` / ``output``), ``call_id``
  (or ``tool_call_id`` / ``id``) naming the call it answers.
- ``context``: ``text`` (or ``content``), ``id`` -- a segment of context
  (system prompt, retrieved document, memory block) fed to the model.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass

KNOWN_TYPES = ("reasoning", "text", "tool_call", "tool_result", "context")

_TEXT_FIELDS = {
    "reasoning": ("text", "content", "reasoning"),
    "text": ("text", "content"),
    "context": ("text", "content"),
    "tool_result": ("result", "content", "output"),
}


class TraceFormatError(ValueError):
    """Raised when a trace line cannot be parsed."""


def estimate_tokens(text: str) -> int:
    """Rough token estimate: one token per four characters, rounded up.

    This is an estimate, not a tokenizer count. It is consistent across
    events, which is what waste *shares* depend on.
    """
    if not text:
        return 0
    return math.ceil(len(text) / 4)


def canonical_json(value) -> str:
    """Deterministic JSON rendering (sorted keys), for comparisons."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        default=str,
    )


def _as_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return canonical_json(value)


def _first(raw: dict, fields) -> object:
    for name in fields:
        if raw.get(name) is not None:
            return raw[name]
    return None


@dataclass
class Event:
    """One event in an agent run trace."""

    index: int
    type: str
    raw: dict
    id: str | None = None
    text: str = ""
    tool: str | None = None
    args: object = None
    call_id: str | None = None
    refs: tuple = ()
    tokens: int = 0

    @property
    def args_key(self) -> str:
        """Canonical rendering of the tool-call arguments."""
        if self.args is None:
            return ""
        return canonical_json(self.args)


def event_from_dict(index: int, raw: dict) -> Event:
    """Build an Event from one parsed JSON object, tolerantly."""
    raw_type = str(raw.get("type") or "other").strip().lower()
    etype = raw_type if raw_type in KNOWN_TYPES else "other"

    event_id = raw.get("id")
    if event_id is None and etype == "tool_call":
        event_id = raw.get("call_id")
    if event_id is not None:
        event_id = str(event_id)

    call_id = _first(raw, ("call_id", "tool_call_id"))
    if call_id is None and etype == "tool_result":
        call_id = raw.get("id")
    if call_id is not None:
        call_id = str(call_id)

    tool = _first(raw, ("tool", "name"))
    args = raw.get("args", raw.get("arguments"))

    if etype == "tool_call":
        text = ((str(tool) + " ") if tool else "") + canonical_json(args)
    elif etype in _TEXT_FIELDS:
        text = _as_text(_first(raw, _TEXT_FIELDS[etype]))
    else:
        text = canonical_json(raw)

    refs_raw = raw.get("refs") or ()
    refs = tuple(str(r) for r in refs_raw) if isinstance(refs_raw, list) else ()

    tokens_field = raw.get("tokens")
    if isinstance(tokens_field, int) and not isinstance(tokens_field, bool) \
            and tokens_field >= 0:
        tokens = tokens_field
    else:
        tokens = estimate_tokens(text)

    return Event(
        index=index,
        type=etype,
        raw=raw,
        id=event_id,
        text=text,
        tool=str(tool) if tool is not None else None,
        args=args,
        call_id=call_id,
        refs=refs,
        tokens=tokens,
    )


def parse_trace(text: str) -> list[Event]:
    """Parse JSONL trace text into a list of Events.

    Raises TraceFormatError, naming the offending line, on malformed JSON
    or on a line that is not a JSON object.
    """
    events: list[Event] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise TraceFormatError(f"line {lineno}: invalid JSON: {exc}") from exc
        if not isinstance(raw, dict):
            raise TraceFormatError(f"line {lineno}: expected a JSON object")
        events.append(event_from_dict(len(events), raw))
    return events
