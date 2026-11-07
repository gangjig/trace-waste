# trace-waste

Audit an AI agent's run trace for wasted tokens: repeated tool calls,
redundant reasoning, and results and context that nothing ever used again.

## Why

A 2026 study of agent traces (see Source below) found that 41–46% of the
reasoning content in agent runs could be pruned online while the tasks
still passed — and that how much gets wasted depends more on the task and
the harness (the prompts, tools, and control flow around the model) than
on the model itself. In other words, a large share of what you pay for in
an agent run is often removable waste, and the lever is your harness, not
a cheaper model.

trace-waste makes that waste visible in your own traces. It reads one
run, labels the wasteful parts, groups them by category, and tells you
how many tokens each category accounts for, what share of the whole run
that is, and what you would save by pruning it.

## Quickstart

```bash
pip install -e .          # or: pip install trace-waste (once published)

trace-waste analyze examples/sample-trace.jsonl
trace-waste demo                    # analyze a built-in sample trace
trace-waste analyze run.jsonl --json --price-per-1m 3.00
cat run.jsonl | trace-waste analyze - --fail-above 25   # CI gate
```

Sample output:

```text
trace-waste report
events: 11   total tokens (est.): 205

waste by category:
  redundant-reasoning    1 findings        34 tokens   16.6%
  repeated-tool-call     1 findings        23 tokens   11.2%
  unused-tool-result     1 findings        23 tokens   11.2%
  unused-context         1 findings        23 tokens   11.2%

total waste: 103 tokens (50.2% of the run)
estimated savings if pruned: 103 tokens
```

## Trace format

The input is JSONL: one JSON object per line, one object per event, in
run order. Parsing is tolerant — unknown event types are kept and counted
toward the total but not waste-checked, blank lines are skipped, and most
fields are optional.

| type          | fields it reads                                                        |
|---------------|------------------------------------------------------------------------|
| `reasoning`   | `text` (or `content`); optional `id`, `refs`                            |
| `text`        | `text` (or `content`); optional `id`, `refs`                            |
| `tool_call`   | `tool` (or `name`), `args` (or `arguments`), `id` (or `call_id`)        |
| `tool_result` | `result` (or `content` / `output`); `call_id` (or `tool_call_id` / `id`) naming the call it answers |
| `context`     | `text` (or `content`), `id` — a segment of context fed to the model (system prompt, retrieved document, memory block) |

Two cross-event fields matter for the waste checks:

- `refs`: a list of ids of earlier events that this step explicitly used.
- `tokens`: an event may carry its true token count as an integer. When
  it does not, the count is estimated (see the caveat below).

A `tool_result` is paired with the call whose id matches its `call_id`;
failing that, with the earliest earlier call that has no result yet.

## Waste categories

- **`repeated-tool-call`** — the same tool called again with identical
  arguments, producing the identical result (or no result at all). The
  repeat call and its result are waste. A repeat that returns a *different*
  result is treated as a deliberate re-check and is not flagged.
- **`redundant-reasoning`** — a reasoning or text block whose word overlap
  (Jaccard similarity) with an earlier block is at or above the
  `--similarity` threshold (default 0.8). Blocks with fewer than four
  distinct words are ignored.
- **`unused-tool-result`** — a tool result that no later step references.
- **`unused-context`** — a context segment that no later step references.

A tool result or context segment counts as *referenced* when a later step
lists its id in `refs`, mentions its id in its text, or quotes its text
(the full text, or its first 30 normalized characters when longer).

Token accounting never double-counts: each event's tokens can be counted
as waste at most once, even when two categories point at the same event.

## Judges

Detection is done by a *judge*, behind a small pluggable interface
(`trace_waste.judge.Judge`).

- **Default: the heuristic judge.** Deterministic, offline, no API key —
  the four heuristics above. This is what runs unless you say otherwise.
- **Optional: an external judge command** (`--judge-command CMD`), off by
  default. The command receives the events as a JSON array on stdin and
  must print a JSON array of findings:
  `[{"index": 3, "category": "...", "reason": "..."}]`. This is the hook
  for pointing an LLM (or your own stricter checker) at the trace. When a
  command judge is configured it *replaces* the heuristics rather than
  merging with them; its findings claim the tokens of the event they name.

## Token estimate caveat

Unless an event carries its own `tokens` value, token counts are a
**characters / 4 estimate** (rounded up), not a real tokenizer count.
Treat absolute numbers as approximations. The waste *shares* and the
ranking of categories are the reliable part: the same estimate is applied
consistently to every event, so a category that dominates under the
estimate dominates under any reasonable tokenizer too.

## Exit codes

- `0` — report produced; with `--fail-above PCT`, the waste share is at
  or below PCT.
- `1` — waste share above the `--fail-above PCT` threshold.
- `2` — the trace could not be read or parsed, the judge command failed,
  or the arguments were invalid.

`--price-per-1m USD` converts the estimated savings into dollars at the
given price per million tokens, in both the text and JSON reports.

## Development

```bash
python -m pytest     # standard library only; no third-party dependencies
```

## Source

Inspired by the paper "How Do AI Agents Waste Your Money?"
(arXiv:2611.07238, https://arxiv.org/abs/2611.07238), which measured how
much of an agent's reasoning can be pruned without changing task
outcomes, and found the waste is mostly a property of the task and the
harness. Surfaced in the author's daily AI digest, 2026-11-07.

## Build your own

This repository is small enough to regenerate from a prompt. Paste the
following into an LLM and it should produce a closely similar project:

> Write a small Python command-line tool called "trace-waste" that audits
> AI agent run traces for wasted tokens. It reads a JSONL trace of one
> agent run — reasoning steps, text steps, tool calls, tool results, and
> context segments — and detects four kinds of waste: a tool called again
> with the same arguments returning the same result; reasoning blocks
> that near-duplicate an earlier block; tool results that no later step
> ever references; and context segments that are never referenced again.
> It reports, per waste category and in total, how many tokens the waste
> accounts for, what share of the whole run that is, and what pruning it
> would save, in a human-readable summary and as JSON, with exit codes
> suitable for gating CI on a maximum waste share. Detection is
> deterministic and fully offline by default, behind a pluggable judge
> interface, with an optional hook that lets an external command act as
> the judge instead; token counts are an honest, documented
> characters-divided-by-four estimate unless a trace event supplies its
> own count. The tool must be careful never to count the same event's
> tokens as waste twice, and it should ship with a small demo trace that
> exhibits every waste category.

## License

MIT
